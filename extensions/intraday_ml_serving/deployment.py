"""Production deployment management for ML models."""

import os
import json
import yaml
import logging
import subprocess
import time
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import shutil
import hashlib

try:
    import docker
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    docker = None

try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False
    client = None
    config = None
    ApiException = None

from extensions.intraday_ml_models.registry import MLModelRegistry
from extensions.intraday_ml_serving.model_server import ModelServer


@dataclass
class DeploymentConfig:
    """Configuration for model deployment."""
    deployment_name: str
    model_id: str
    replicas: int = 1
    cpu_limit: str = "500m"
    memory_limit: str = "1Gi"
    cpu_request: str = "100m"
    memory_request: str = "256Mi"
    environment: str = "production"
    health_check_path: str = "/health"
    metrics_path: str = "/metrics"
    port: int = 8000
    image_tag: str = "latest"
    auto_scaling: Optional[Dict[str, Any]] = None
    resources: Optional[Dict[str, str]] = None


@dataclass
class DeploymentStatus:
    """Status of model deployment."""
    deployment_name: str
    status: str  # pending, running, failed, stopped
    replicas: int
    ready_replicas: int
    created_at: datetime
    updated_at: datetime
    endpoint_url: Optional[str] = None
    health_status: str = "unknown"
    version: str = "unknown"
    error_message: Optional[str] = None


class MockDeployment:
    """Mock deployment for testing when dependencies unavailable."""

    def __init__(self, deployment_type: str):
        self.deployment_type = deployment_type
        self.logger = logging.getLogger(__name__)

    def deploy_model(self, model_id: str, **kwargs) -> DeploymentStatus:
        """Mock deployment."""
        return DeploymentStatus(
            deployment_name=f"mock-{model_id}",
            status="running",
            replicas=1,
            ready_replicas=1,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            endpoint_url=f"http://mock-endpoint/{model_id}",
            version="mock-1.0.0"
        )

    def get_deployment_status(self, deployment_name: str) -> DeploymentStatus:
        """Mock status check."""
        return DeploymentStatus(
            deployment_name=deployment_name,
            status="running",
            replicas=1,
            ready_replicas=1,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )


class DockerDeployment:
    """Docker-based deployment for ML models."""

    def __init__(self, registry_url: Optional[str] = None):
        """
        Initialize Docker deployment manager.

        Args:
            registry_url: Docker registry URL for pushing images
        """
        self.registry_url = registry_url
        if DOCKER_AVAILABLE:
            self.client = docker.from_env()
        else:
            self.client = None
        self.logger = logging.getLogger(__name__)

    def build_image(
        self,
        model_id: str,
        dockerfile_path: str,
        context_path: str,
        tag: Optional[str] = None
    ) -> str:
        """
        Build Docker image for model.

        Args:
            model_id: Model identifier
            dockerfile_path: Path to Dockerfile
            context_path: Build context path
            tag: Image tag (defaults to model_id)

        Returns:
            Image tag
        """
        if tag is None:
            tag = f"intraday-ml:{model_id}"

        self.logger.info(f"Building Docker image {tag} for model {model_id}")

        try:
            image, build_logs = self.client.images.build(
                path=context_path,
                dockerfile=dockerfile_path,
                tag=tag,
                rm=True,
                buildargs={
                    "MODEL_ID": model_id,
                    "BUILD_DATE": datetime.now().isoformat()
                }
            )

            # Log build progress
            for log in build_logs:
                if "stream" in log:
                    self.logger.info(log["stream"].strip())

            self.logger.info(f"Successfully built image {tag}")
            return tag

        except docker.errors.BuildError as e:
            self.logger.error(f"Docker build failed: {e}")
            raise

    def push_image(self, image_tag: str) -> str:
        """
        Push Docker image to registry.

        Args:
            image_tag: Image tag to push

        Returns:
            Pushed image tag
        """
        if not self.registry_url:
            raise ValueError("Registry URL not configured")

        full_tag = f"{self.registry_url}/{image_tag}"
        self.logger.info(f"Pushing image {full_tag}")

        try:
            # Tag image for registry
            image = self.client.images.get(image_tag)
            image.tag(full_tag, tag="latest")

            # Push image
            push_logs = self.client.images.push(full_tag, tag="latest", stream=True)

            for log in push_logs:
                if "status" in log:
                    self.logger.info(f"Push: {log['status']}")

            self.logger.info(f"Successfully pushed image {full_tag}")
            return full_tag

        except docker.errors.APIError as e:
            self.logger.error(f"Docker push failed: {e}")
            raise

    def run_container(
        self,
        image_tag: str,
        deployment_config: DeploymentConfig
    ) -> str:
        """
        Run Docker container for model deployment.

        Args:
            image_tag: Docker image tag
            deployment_config: Deployment configuration

        Returns:
            Container ID
        """
        self.logger.info(f"Running container for {deployment_config.deployment_name}")

        try:
            container = self.client.containers.run(
                image_tag,
                name=deployment_config.deployment_name,
                ports={f"{deployment_config.port}/tcp": deployment_config.port},
                environment={
                    "MODEL_ID": deployment_config.model_id,
                    "ENVIRONMENT": deployment_config.environment,
                    "LOG_LEVEL": "INFO"
                },
                mem_limit=deployment_config.memory_limit,
                nano_cpus=self._parse_cpu_limit(deployment_config.cpu_limit),
                detach=True,
                restart_policy={"Name": "unless-stopped"},
                healthcheck={
                    "test": f"CMD curl -f {deployment_config.health_check_path} || exit 1",
                    "interval": 30000000000,  # 30 seconds in nanoseconds
                    "timeout": 5000000000,     # 5 seconds
                    "retries": 3
                }
            )

            self.logger.info(f"Container started with ID: {container.id}")
            return container.id

        except docker.errors.APIError as e:
            self.logger.error(f"Failed to run container: {e}")
            raise

    def stop_container(self, container_id: str):
        """Stop and remove Docker container."""
        try:
            container = self.client.containers.get(container_id)
            container.stop()
            container.remove()
            self.logger.info(f"Stopped container {container_id}")
        except docker.errors.NotFound:
            self.logger.warning(f"Container {container_id} not found")
        except docker.errors.APIError as e:
            self.logger.error(f"Failed to stop container {container_id}: {e}")

    def get_container_status(self, container_id: str) -> Dict[str, Any]:
        """Get container status."""
        try:
            container = self.client.containers.get(container_id)
            status = container.status()
            health = container.attrs.get("State", {}).get("Health", {})

            return {
                "status": status,
                "health": health.get("Status", "unknown"),
                "created": container.attrs["Created"],
                "started": container.attrs["State"]["StartedAt"],
                "finished": container.attrs["State"]["FinishedAt"],
                "exit_code": container.attrs["State"]["ExitCode"]
            }

        except docker.errors.NotFound:
            return {"status": "not_found", "health": "unknown"}

    def _parse_cpu_limit(self, cpu_limit: str) -> int:
        """Parse CPU limit string to nanoseconds."""
        if cpu_limit.endswith("m"):
            # millicores
            millicores = int(cpu_limit[:-1])
            return millicores * 1_000_000
        else:
            # cores
            cores = float(cpu_limit)
            return int(cores * 1_000_000_000)


class KubernetesDeployment:
    """Kubernetes-based deployment for ML models."""

    def __init__(self, namespace: str = "default", kubeconfig_path: Optional[str] = None):
        """
        Initialize Kubernetes deployment manager.

        Args:
            namespace: Kubernetes namespace
            kubeconfig_path: Path to kubeconfig file
        """
        self.namespace = namespace

        try:
            if kubeconfig_path:
                config.load_kube_config(config_file=kubeconfig_path)
            else:
                config.load_incluster_config()  # For running inside cluster
        except Exception:
            config.load_kube_config()  # Fallback to default

        self.apps_v1 = client.AppsV1Api()
        self.core_v1 = client.CoreV1Api()
        self.autoscaling_v1 = client.AutoscalingV1Api()
        self.logger = logging.getLogger(__name__)

    def create_deployment(self, deployment_config: DeploymentConfig, image_tag: str) -> str:
        """
        Create Kubernetes deployment.

        Args:
            deployment_config: Deployment configuration
            image_tag: Docker image tag

        Returns:
            Deployment name
        """
        self.logger.info(f"Creating Kubernetes deployment {deployment_config.deployment_name}")

        # Create deployment manifest
        deployment_manifest = self._create_deployment_manifest(deployment_config, image_tag)

        try:
            deployment = self.apps_v1.create_namespaced_deployment(
                namespace=self.namespace,
                body=deployment_manifest
            )

            # Create service
            service_manifest = self._create_service_manifest(deployment_config)
            self.core_v1.create_namespaced_service(
                namespace=self.namespace,
                body=service_manifest
            )

            # Create HPA if auto-scaling enabled
            if deployment_config.auto_scaling:
                hpa_manifest = self._create_hpa_manifest(deployment_config)
                self.autoscaling_v1.create_namespaced_horizontal_pod_autoscaler(
                    namespace=self.namespace,
                    body=hpa_manifest
                )

            self.logger.info(f"Successfully created deployment {deployment_config.deployment_name}")
            return deployment.metadata.name

        except ApiException as e:
            self.logger.error(f"Failed to create deployment: {e}")
            raise

    def update_deployment(self, deployment_config: DeploymentConfig, image_tag: str) -> str:
        """
        Update existing Kubernetes deployment.

        Args:
            deployment_config: Deployment configuration
            image_tag: New Docker image tag

        Returns:
            Deployment name
        """
        self.logger.info(f"Updating Kubernetes deployment {deployment_config.deployment_name}")

        try:
            # Get existing deployment
            existing_deployment = self.apps_v1.read_namespaced_deployment(
                name=deployment_config.deployment_name,
                namespace=self.namespace
            )

            # Update image
            existing_deployment.spec.template.spec.containers[0].image = image_tag
            existing_deployment.spec.template.spec.containers[0].env = [
                client.V1EnvVar(name="MODEL_ID", value=deployment_config.model_id),
                client.V1EnvVar(name="ENVIRONMENT", value=deployment_config.environment),
                client.V1EnvVar(name="LOG_LEVEL", value="INFO")
            ]

            # Update resource limits
            existing_deployment.spec.template.spec.containers[0].resources = client.V1ResourceRequirements(
                requests={
                    "cpu": deployment_config.cpu_request,
                    "memory": deployment_config.memory_request
                },
                limits={
                    "cpu": deployment_config.cpu_limit,
                    "memory": deployment_config.memory_limit
                }
            )

            # Update deployment
            updated_deployment = self.apps_v1.patch_namespaced_deployment(
                name=deployment_config.deployment_name,
                namespace=self.namespace,
                body=existing_deployment
            )

            self.logger.info(f"Successfully updated deployment {deployment_config.deployment_name}")
            return updated_deployment.metadata.name

        except ApiException as e:
            self.logger.error(f"Failed to update deployment: {e}")
            raise

    def delete_deployment(self, deployment_name: str):
        """Delete Kubernetes deployment."""
        self.logger.info(f"Deleting deployment {deployment_name}")

        try:
            # Delete HPA
            try:
                self.autoscaling_v1.delete_namespaced_horizontal_pod_autoscaler(
                    name=deployment_name,
                    namespace=self.namespace
                )
            except ApiException:
                pass  # HPA might not exist

            # Delete deployment
            self.apps_v1.delete_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace
            )

            # Delete service
            self.core_v1.delete_namespaced_service(
                name=deployment_name,
                namespace=self.namespace
            )

            self.logger.info(f"Successfully deleted deployment {deployment_name}")

        except ApiException as e:
            self.logger.error(f"Failed to delete deployment: {e}")
            raise

    def get_deployment_status(self, deployment_name: str) -> DeploymentStatus:
        """Get deployment status."""
        try:
            deployment = self.apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace
            )

            service = self.core_v1.read_namespaced_service(
                name=deployment_name,
                namespace=self.namespace
            )

            status = deployment.status
            health_status = "unknown"

            # Check pod health
            if status.ready_replicas == status.replicas and status.replicas > 0:
                health_status = "healthy"
            elif status.replicas > 0:
                health_status = "degraded"
            else:
                health_status = "unhealthy"

            # Get endpoint URL
            endpoint_url = None
            if service.spec.type == "LoadBalancer" and service.status.load_balancer:
                if service.status.load_balancer.ingress:
                    endpoint_url = f"http://{service.status.load_balancer.ingress[0].ip}:{deployment_name}.{self.namespace}.svc.cluster.local:{deployment.spec.template.spec.containers[0].ports[0].container_port}"
            else:
                endpoint_url = f"http://{deployment_name}.{self.namespace}.svc.cluster.local:{deployment.spec.template.spec.containers[0].ports[0].container_port}"

            return DeploymentStatus(
                deployment_name=deployment_name,
                status="running",
                replicas=status.replicas or 0,
                ready_replicas=status.ready_replicas or 0,
                created_at=deployment.metadata.creation_timestamp,
                updated_at=datetime.now(),
                endpoint_url=endpoint_url,
                health_status=health_status,
                version=deployment.spec.template.spec.containers[0].image.split(":")[-1]
            )

        except ApiException as e:
            if e.status == 404:
                return DeploymentStatus(
                    deployment_name=deployment_name,
                    status="not_found",
                    replicas=0,
                    ready_replicas=0,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                    health_status="unknown"
                )
            else:
                self.logger.error(f"Failed to get deployment status: {e}")
                raise

    def _create_deployment_manifest(self, config: DeploymentConfig, image_tag: str) -> Dict[str, Any]:
        """Create Kubernetes deployment manifest."""
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": config.deployment_name,
                "labels": {
                    "app": config.deployment_name,
                    "model": config.model_id
                }
            },
            "spec": {
                "replicas": config.replicas,
                "selector": {
                    "matchLabels": {
                        "app": config.deployment_name
                    }
                },
                "template": {
                    "metadata": {
                        "labels": {
                            "app": config.deployment_name,
                            "model": config.model_id
                        }
                    },
                    "spec": {
                        "containers": [{
                            "name": "ml-model",
                            "image": image_tag,
                            "ports": [{
                                "containerPort": config.port,
                                "protocol": "TCP"
                            }],
                            "env": [
                                {"name": "MODEL_ID", "value": config.model_id},
                                {"name": "ENVIRONMENT", "value": config.environment},
                                {"name": "LOG_LEVEL", "value": "INFO"}
                            ],
                            "resources": {
                                "requests": {
                                    "cpu": config.cpu_request,
                                    "memory": config.memory_request
                                },
                                "limits": {
                                    "cpu": config.cpu_limit,
                                    "memory": config.memory_limit
                                }
                            },
                            "readinessProbe": {
                                "httpGet": {
                                    "path": config.health_check_path,
                                    "port": config.port
                                },
                                "initialDelaySeconds": 30,
                                "periodSeconds": 10
                            },
                            "livenessProbe": {
                                "httpGet": {
                                    "path": config.health_check_path,
                                    "port": config.port
                                },
                                "initialDelaySeconds": 60,
                                "periodSeconds": 30
                            }
                        }]
                    }
                }
            }
        }

    def _create_service_manifest(self, config: DeploymentConfig) -> Dict[str, Any]:
        """Create Kubernetes service manifest."""
        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": config.deployment_name,
                "labels": {
                    "app": config.deployment_name
                }
            },
            "spec": {
                "selector": {
                    "app": config.deployment_name
                },
                "ports": [{
                    "port": config.port,
                    "targetPort": config.port,
                    "protocol": "TCP"
                }],
                "type": "ClusterIP"
            }
        }

    def _create_hpa_manifest(self, config: DeploymentConfig) -> Dict[str, Any]:
        """Create Kubernetes HPA manifest."""
        return {
            "apiVersion": "autoscaling/v1",
            "kind": "HorizontalPodAutoscaler",
            "metadata": {
                "name": config.deployment_name,
                "labels": {
                    "app": config.deployment_name
                }
            },
            "spec": {
                "scaleTargetRef": {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": config.deployment_name
                },
                "minReplicas": config.auto_scaling.get("min_replicas", 1),
                "maxReplicas": config.auto_scaling.get("max_replicas", 10),
                "targetCPUUtilizationPercentage": config.auto_scaling.get("target_cpu", 70)
            }
        }


class DeploymentManager:
    """Manages deployment of ML models to production."""

    def __init__(
        self,
        registry: Optional[MLModelRegistry] = None,
        deployment_type: str = "docker",
        **kwargs
    ):
        """
        Initialize deployment manager.

        Args:
            registry: Model registry
            deployment_type: Type of deployment ("docker" or "kubernetes")
            **kwargs: Additional arguments for deployment backend
        """
        self.registry = registry or MLModelRegistry()
        self.deployment_type = deployment_type
        self.logger = logging.getLogger(__name__)

        if deployment_type == "docker" and DOCKER_AVAILABLE:
            self.deployer = DockerDeployment(**kwargs)
        elif deployment_type == "kubernetes" and K8S_AVAILABLE:
            self.deployer = KubernetesDeployment(**kwargs)
        else:
            # Create a mock deployer for testing
            self.deployer = MockDeployment(deployment_type)
            self.logger.warning(f"Using mock deployment for {deployment_type} - dependencies not available")
        self.deployments: Dict[str, DeploymentStatus] = {}

    def deploy_model(
        self,
        model_id: str,
        deployment_config: DeploymentConfig,
        dockerfile_path: Optional[str] = None,
        context_path: Optional[str] = None,
        image_tag: Optional[str] = None
    ) -> DeploymentStatus:
        """
        Deploy model to production.

        Args:
            model_id: Model to deploy
            deployment_config: Deployment configuration
            dockerfile_path: Path to Dockerfile (required for Docker deployment)
            context_path: Build context path (required for Docker deployment)
            image_tag: Pre-built image tag (optional)

        Returns:
            Deployment status
        """
        self.logger.info(f"Deploying model {model_id} with config {deployment_config.deployment_name}")

        try:
            # Validate model exists
            model_metadata = self.registry.get_metadata(model_id)

            # Build or use existing image
            if image_tag is None:
                if self.deployment_type == "docker":
                    if not dockerfile_path or not context_path:
                        raise ValueError("dockerfile_path and context_path required for Docker deployment")

                    image_tag = self.deployer.build_image(
                        model_id=model_id,
                        dockerfile_path=dockerfile_path,
                        context_path=context_path,
                        tag=f"intraday-ml:{model_id}"
                    )
                else:
                    image_tag = f"intraday-ml:{model_id}"

            # Deploy based on type
            if self.deployment_type == "docker":
                container_id = self.deployer.run_container(image_tag, deployment_config)
                deployment_id = container_id
                endpoint_url = f"http://localhost:{deployment_config.port}"
            else:
                deployment_id = self.deployer.create_deployment(deployment_config, image_tag)
                status = self.deployer.get_deployment_status(deployment_config.deployment_name)
                endpoint_url = status.endpoint_url

            # Create deployment status
            deployment_status = DeploymentStatus(
                deployment_name=deployment_config.deployment_name,
                status="running",
                replicas=deployment_config.replicas,
                ready_replicas=deployment_config.replicas,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                endpoint_url=endpoint_url,
                health_status="healthy",
                version=model_metadata.model_hash[:8]
            )

            self.deployments[deployment_config.deployment_name] = deployment_status

            self.logger.info(f"Successfully deployed model {model_id}")
            return deployment_status

        except Exception as e:
            self.logger.error(f"Failed to deploy model {model_id}: {e}")
            error_status = DeploymentStatus(
                deployment_name=deployment_config.deployment_name,
                status="failed",
                replicas=0,
                ready_replicas=0,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                error_message=str(e)
            )
            self.deployments[deployment_config.deployment_name] = error_status
            raise

    def update_deployment(
        self,
        deployment_name: str,
        model_id: Optional[str] = None,
        image_tag: Optional[str] = None
    ) -> DeploymentStatus:
        """Update existing deployment."""
        if deployment_name not in self.deployments:
            raise ValueError(f"Deployment {deployment_name} not found")

        self.logger.info(f"Updating deployment {deployment_name}")

        try:
            if self.deployment_type == "docker":
                # For Docker, we need to stop and restart
                self.undeploy_model(deployment_name)
                # This would require the original deployment config
                raise NotImplementedError("Docker update not implemented yet")
            else:
                # For Kubernetes, we can update in place
                if image_tag is None:
                    image_tag = f"intraday-ml:{model_id}"

                # Get existing config (would need to store this)
                deployment_config = DeploymentConfig(
                    deployment_name=deployment_name,
                    model_id=model_id or "unknown"
                )

                self.deployer.update_deployment(deployment_config, image_tag)
                status = self.deployer.get_deployment_status(deployment_name)

                self.deployments[deployment_name] = status
                return status

        except Exception as e:
            self.logger.error(f"Failed to update deployment {deployment_name}: {e}")
            raise

    def undeploy_model(self, deployment_name: str):
        """Remove model deployment."""
        if deployment_name not in self.deployments:
            self.logger.warning(f"Deployment {deployment_name} not found")
            return

        self.logger.info(f"Undeploying {deployment_name}")

        try:
            if self.deployment_type == "docker":
                # Docker deployment - stop container
                deployment_status = self.deployments[deployment_name]
                if hasattr(deployment_status, 'container_id'):
                    self.deployer.stop_container(deployment_status.container_id)
            else:
                # Kubernetes deployment - delete deployment
                self.deployer.delete_deployment(deployment_name)

            del self.deployments[deployment_name]
            self.logger.info(f"Successfully undeployed {deployment_name}")

        except Exception as e:
            self.logger.error(f"Failed to undeploy {deployment_name}: {e}")
            raise

    def get_deployment_status(self, deployment_name: str) -> Optional[DeploymentStatus]:
        """Get deployment status."""
        if deployment_name not in self.deployments:
            return None

        try:
            if self.deployment_type == "docker":
                # Docker deployment
                deployment_status = self.deployments[deployment_name]
                if hasattr(deployment_status, 'container_id'):
                    container_status = self.deployer.get_container_status(deployment_status.container_id)
                    deployment_status.health_status = container_status.get("health", "unknown")
                    deployment_status.status = container_status.get("status", "unknown")
            else:
                # Kubernetes deployment
                deployment_status = self.deployer.get_deployment_status(deployment_name)
                self.deployments[deployment_name] = deployment_status

            return self.deployments[deployment_name]

        except Exception as e:
            self.logger.error(f"Failed to get deployment status for {deployment_name}: {e}")
            return None

    def list_deployments(self) -> List[DeploymentStatus]:
        """List all deployments."""
        deployments = []
        for deployment_name in list(self.deployments.keys()):
            status = self.get_deployment_status(deployment_name)
            if status:
                deployments.append(status)

        return deployments

    def health_check(self, deployment_name: str) -> Dict[str, Any]:
        """Perform health check on deployment."""
        status = self.get_deployment_status(deployment_name)
        if not status:
            return {"healthy": False, "error": "Deployment not found"}

        if status.endpoint_url is None:
            return {"healthy": False, "error": "No endpoint URL"}

        try:
            import requests
            response = requests.get(
                f"{status.endpoint_url}{status.health_check_path}",
                timeout=10
            )
            return {
                "healthy": response.status_code == 200,
                "status_code": response.status_code,
                "response_time_ms": response.elapsed.total_seconds() * 1000
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}