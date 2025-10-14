# Governance Framework

Comprehensive governance framework for QuantStack development, testing, deployment, and maintenance.

## Overview

This governance framework establishes standards, processes, and responsibilities for ensuring the quality, reliability, and reproducibility of the QuantStack quantitative trading platform. It covers code development, experimentation, deployment, and operational procedures.

## Development Governance

### Code Standards

#### Style Guidelines

All Python code must adhere to the following standards:

```bash
# Code formatting
black --line-length 100 qx-*/src/

# Import sorting
isort qx-*/src/

# Linting
flake8 qx-*/src/ --max-line-length 100 --ignore=E203,W503

# Type checking
mypy qx-*/src/ --ignore-missing-imports
```

#### Naming Conventions

- **Packages**: `kebab-case` (e.g., `qx-backtest`)
- **Modules**: `snake_case` (e.g., `engine.py`)
- **Classes**: `PascalCase` (e.g., `BacktestEngine`)
- **Functions**: `snake_case` (e.g., `calculate_signals()`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_POSITIONS`)
- **File Names**: `snake_case` for files, `kebab-case` for directories

#### Documentation Standards

```python
def calculate_vwap(bars: pd.DataFrame, window_minutes: int = 30) -> pd.Series:
    """
    Calculate Volume-Weighted Average Price (VWAP) over a rolling window.

    Args:
        bars: DataFrame with columns [ts, symbol, close, volume]
        window_minutes: Rolling window size in minutes

    Returns:
        Series containing VWAP values aligned with input DataFrame

    Raises:
        ValueError: If required columns are missing from bars DataFrame

    Example:
        >>> bars = pd.DataFrame({
        ...     'close': [100.0, 101.0, 102.0],
        ...     'volume': [1000, 1100, 900]
        ... })
        >>> vwap = calculate_vwap(bars, window_minutes=30)
    """
    pass
```

### Code Review Process

#### Pull Request Requirements

All changes must be submitted via Pull Request with:

1. **Clear Description**: Purpose and impact of changes
2. **Test Coverage**: New or updated tests
3. **Documentation**: Updated docstrings and relevant documentation
4. **Schema Changes**: Schema impact analysis if applicable
5. **Breaking Changes**: Clearly marked and justified

#### Review Checklist

```markdown
## Code Review Checklist

### Functionality
- [ ] Code implements intended functionality
- [ ] Edge cases are handled appropriately
- [ ] Error handling is comprehensive
- [ ] Performance implications considered

### Testing
- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Reproducibility tests pass
- [ ] Coverage requirements met (≥80%)

### Documentation
- [ ] Docstrings complete and accurate
- [ ] API documentation updated
- [ ] Schema documentation updated
- [ ] Examples provided where appropriate

### Standards
- [ ] Code style compliance (black, isort, flake8)
- [ ] Type hints provided
- [ ] Naming conventions followed
- [ ] Security considerations addressed

### Reproducibility
- [ ] Deterministic behavior ensured
- [ ] Random seeds properly handled
- [ ] Schema compliance maintained
- [ ] Hash stability preserved
```

### Branching Strategy

```
main                    # Production-ready code
├── develop            # Integration branch
├── feature/*          # Feature development
├── hotfix/*           # Production fixes
└── release/*          # Release preparation
```

#### Branch Protection Rules

- **main**: Requires PR approval, CI pass, and no force pushes
- **develop**: Requires PR approval and CI pass
- **feature/***: Standard PR workflow
- **hotfix/***: Expedited review, still requires CI

## Testing Governance

### Testing Pyramid

```
    ┌─────────────────┐
    │  E2E Smoke Tests │  ← Few, comprehensive system tests
    └─────────────────┘
          ┌─────────────────┐
          │ Integration Tests│  ← Component interaction tests
          └─────────────────┘
                ┌─────────────────┐
                │  Unit Tests     │  ← Many, isolated function tests
                └─────────────────┘
```

### Test Requirements

#### Unit Tests

- **Coverage**: ≥80% line coverage for all modules
- **Scope**: Test individual functions and classes in isolation
- **Speed**: Each test should run in <10ms
- **Determinism**: Tests must produce identical results across runs

```python
# Example unit test
import pytest
import pandas as pd
from qx_features.core_basics import calculate_vwap

class TestCalculateVWAP:
    def test_basic_functionality(self):
        """Test VWAP calculation with sample data."""
        bars = pd.DataFrame({
            'ts': pd.date_range('2024-01-01', periods=100, freq='1min'),
            'close': [100 + i * 0.01 for i in range(100)],
            'volume': [1000] * 100
        })

        result = calculate_vwap(bars, window_minutes=30)

        assert len(result) == len(bars)
        assert not result.isna().any()
        assert result.iloc[0] == pytest.approx(100.0)

    def test_missing_columns_error(self):
        """Test that missing columns raise appropriate errors."""
        bars = pd.DataFrame({'wrong_column': [1, 2, 3]})

        with pytest.raises(ValueError, match="Required columns missing"):
            calculate_vwap(bars)
```

#### Integration Tests

- **Scope**: Test interactions between components
- **Data**: Use deterministic test data fixtures
- **Environment**: Isolated test environment
- **Reproducibility**: Validate checksum consistency

```python
# Example integration test
@pytest.mark.integration
class TestFeatureEngineeringPipeline:
    def test_end_to_end_feature_computation(self, sample_gold_data):
        """Test complete feature engineering pipeline."""
        from qx_data.gold_loader import GoldLoader
        from qx_features.registry import apply

        # Load data
        loader = GoldLoader(sample_gold_data.path)
        bars = loader.load_bars(['AAPL'], ['2024-01-01'])

        # Apply features
        features = apply(bars, [
            {'type': 'core_basics', 'params': {'vwap_window_m': 30}},
            {'type': 'vpa', 'params': {'volume_window_m': 20}}
        ])

        # Validate results
        assert 'f__vwap' in features.columns
        assert 'p__vpa__volume_spike' in features.columns
        assert not features[['f__vwap', 'p__vpa__volume_spike']].isna().any().any()

        # Validate reproducibility
        hash1 = hash_dataframe(features)
        hash2 = hash_dataframe(features)
        assert hash1 == hash2
```

#### Reproducibility Tests

- **Scope**: Validate deterministic behavior across runs
- **Hash Validation**: Ensure input/output hash consistency
- **Seed Testing**: Verify random seed control
- **Schema Compliance**: Validate schema adherence

```python
# Example reproducibility test
@pytest.mark.reproducibility
class TestHashStability:
    def test_identical_inputs_produce_identical_hashes(self, sample_data):
        """Test that identical data produces identical hashes."""
        from qx_core.hashers import hash_dataframe

        hash1 = hash_dataframe(sample_data)
        hash2 = hash_dataframe(sample_data)

        assert hash1 == hash2, "Identical data should produce identical hashes"

    def test_deterministic_feature_computation(self, sample_data):
        """Test that feature computation is deterministic."""
        from qx_features.registry import apply

        features1 = apply(sample_data.copy(), [
            {'type': 'core_basics', 'params': {'vwap_window_m': 30}}
        ])
        features2 = apply(sample_data.copy(), [
            {'type': 'core_basics', 'params': {'vwap_window_m': 30}}
        ])

        hash1 = hash_dataframe(features1)
        hash2 = hash_dataframe(features2)

        assert hash1 == hash2, "Feature computation should be deterministic"
```

### CI/CD Testing Pipeline

```yaml
# .github/workflows/ci.yml
name: QuantStack CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.11, 3.12]

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          pip install -e .[dev,testing]
          pip install pytest pytest-cov pytest-xdist

      - name: Run linting
        run: |
          black --check .
          isort --check-only .
          flake8 .
          mypy . || echo "MyPy completed"

      - name: Run unit tests
        run: |
          pytest tests/unit/ -xvs --cov=qx_core --cov-report=xml

      - name: Run integration tests
        run: |
          pytest tests/integration/ -xvs

      - name: Run reproducibility tests
        run: |
          pytest tests/test_reproducibility.py -v

      - name: Run E2E smoke tests
        run: |
          python scripts/run_smoke_test.py --comprehensive
```

## Experiment Governance

### Experiment Standards

#### Experiment Design Requirements

1. **Clear Hypothesis**: Each experiment must test a specific hypothesis
2. **Control Variables**: Non-test parameters must be held constant
3. **Sufficient Sample Size**: Minimum 100 trades per variant for statistical significance
4. **Fair Comparison**: Identical input conditions across variants

#### Experiment Naming Convention

```
{strategy}_{parameter_tested}_{variant}_{date}

Examples:
- vwap_revert_rvolThreshold_aggressive_20240115
- momentum_stopLoss_atr_20240116
- portfolio_allocation_equalWeight_20240117
```

#### Experiment Documentation

Each experiment must include:

```yaml
# experiments/configs/experiment_template.yaml
experiment:
  name: "strategy_parameter_test"
  description: "Test hypothesis description"
  hypothesis: "Clear statement of what is being tested"
  author: "username"
  created_at: "2024-01-15T10:00:00Z"

design:
  control_variables:
    - data_slice
    - features
    - seed
    - risk_params

  test_variables:
    - policy.entry_threshold
    - policy.exit_threshold

  success_criteria:
    - "Sharpe ratio improvement ≥0.2"
    - "Max drawdown ≤15%"
    - "Win rate ≥55%"
    - "Minimum 100 trades"
```

### Reproducibility Requirements

#### Hash Validation

All experiments must validate reproducibility through hash consistency:

```python
# Required hash matches for fair comparison
required_hashes = {
    'bars_norm_hash': 'Input data hash',
    'features_hash': 'Feature engineering hash',
    'sip_hash': 'Universe screening hash',
    'seed': 'Random seed for stochastic processes'
}

# Config hash is the only allowed difference
varying_hashes = {
    'config_hash': 'Policy/risk parameter differences'
}
```

#### Deterministic Behavior

- **Fixed Seeds**: All random processes must use fixed seeds
- **Stable Sorting**: Data must be sorted deterministically before processing
- **Type Consistency**: Data types must be normalized for hashing
- **Isolation**: Experiments must not interfere with each other

### Experiment Review Process

#### Pre-Experiment Checklist

```markdown
## Experiment Review Checklist

### Design
- [ ] Clear hypothesis stated
- [ ] Control variables identified
- [ ] Sample size calculated
- [ ] Success criteria defined
- [ ] Risk considerations addressed

### Technical
- [ ] Configuration validation complete
- [ ] Data slice availability confirmed
- [ ] Feature dependencies verified
- [ ] Schema compliance checked
- [ ] Reproducibility safeguards in place

### Documentation
- [ ] Experiment purpose documented
- [ ] Parameter rationale explained
- [ ] Expected outcomes described
- [ ] Interpretation guidelines provided
```

#### Post-Experiment Analysis

```python
# Experiment validation script
def validate_experiment_results(exp_id: str) -> bool:
    """Validate experiment results meet governance standards."""

    # Load results
    manifest = load_manifest(f"experiments/{exp_id}/manifest.json")
    compare_data = load_compare(f"experiments/{exp_id}/compare.json")

    # Validate trade count
    for run_id in manifest['run_ids']:
        metrics = load_metrics(f"runs/{run_id}/metrics.json")
        if metrics['trades'] < 100:
            logger.warning(f"Insufficient trades in {run_id}: {metrics['trades']}")

    # Validate reproducibility
    checksums = load_checksums(f"experiments/{exp_id}/inputs_checksum.json")
    if not validate_hash_consistency(checksums):
        logger.error("Reproducibility validation failed")
        return False

    # Validate statistical significance
    if not statistical_significance_test(compare_data):
        logger.warning("Results may not be statistically significant")

    return True
```

## Deployment Governance

### Release Management

#### Version Control

```
Semantic Versioning: MAJOR.MINOR.PATCH

- MAJOR: Breaking changes (API, schema, interface changes)
- MINOR: New features (backward compatible)
- PATCH: Bug fixes (backward compatible)

Examples:
- 1.0.0: Initial release
- 1.1.0: Add new feature
- 1.1.1: Bug fix
- 2.0.0: Breaking changes
```

#### Release Checklist

```markdown
## Release Checklist

### Code Quality
- [ ] All tests passing (unit, integration, reproducibility)
- [ ] Code coverage ≥80%
- [ ] Documentation updated
- [ ] Schema changes documented
- [ ] Performance benchmarks met

### Testing
- [ ] Full test suite on target Python versions
- [ ] E2E smoke tests passed
- [ ] Reproducibility tests passed
- [ ] Security scan completed
- [ ] Load testing completed (if applicable)

### Documentation
- [ ] CHANGELOG updated
- [ ] API docs updated
- [ ] Schema docs updated
- [ ] Migration guide (for breaking changes)
- [ ] Release notes prepared

### Deployment
- [ ] Staging deployment successful
- [ ] Rollback plan documented
- [ ] Monitoring configured
- [ ] Alert thresholds set
- [ ] Post-deployment validation planned
```

### Environment Management

#### Environment Hierarchy

```
Production (main branch)
    ↑
Staging (develop branch)
    ↑
Testing (feature branches)
    ↑
Development (local)
```

#### Deployment Process

1. **Development**: Feature development in local environment
2. **Testing**: PR to develop branch, automated testing
3. **Staging**: Deploy to staging environment for integration testing
4. **Production**: Merge to main branch, deploy to production

#### Rollback Procedures

```bash
# Immediate rollback (emergency)
kubectl rollout undo deployment/qx-api

# Versioned rollback
git checkout v1.2.3
kubectl apply -f k8s/production/

# Database rollback (if needed)
python scripts/rollback_database.py --to-version v1.2.3
```

## Data Governance

### Data Quality Standards

#### Gold Data Requirements

- **Completeness**: No missing required fields
- **Accuracy**: Price and volume data validated
- **Consistency**: Uniform timezone handling (UTC)
- **Timeliness**: Data available within expected windows

#### Schema Governance

```python
# Schema validation requirements
def validate_data_schema(df: pd.DataFrame, schema_type: str) -> bool:
    """Validate DataFrame complies with schema requirements."""

    schema = get_schema_definition(schema_type)

    # Required columns
    missing_cols = set(schema.required_columns) - set(df.columns)
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    # Data types
    for col, expected_type in schema.column_types.items():
        if col in df.columns and not df[col].dtype == expected_type:
            raise TypeError(f"Column {col} must be {expected_type}")

    # Value constraints
    for col, constraints in schema.constraints.items():
        if col in df.columns:
            validate_constraints(df[col], constraints)

    return True
```

### Data Lineage

#### Lineage Tracking

```python
# Data lineage metadata
lineage_record = {
    'data_id': 'unique_identifier',
    'source': 'gold_data',
    'transformation': 'feature_engineering',
    'parameters': {'vwap_window': 30},
    'timestamp': '2024-01-15T10:00:00Z',
    'parent_ids': ['parent_data_id'],
    'schema_version': 'v1.2.0',
    'checksum': 'data_checksum'
}
```

#### Audit Trail

All data transformations must maintain audit trails:

```python
def audit_transformation(
    input_data: pd.DataFrame,
    output_data: pd.DataFrame,
    transformation: str,
    parameters: dict
) -> str:
    """Create audit record for data transformation."""

    audit_id = generate_uuid()

    audit_record = {
        'audit_id': audit_id,
        'timestamp': datetime.utcnow().isoformat(),
        'transformation': transformation,
        'parameters': parameters,
        'input_checksum': hash_dataframe(input_data),
        'output_checksum': hash_dataframe(output_data),
        'input_rows': len(input_data),
        'output_rows': len(output_data),
        'user': get_current_user()
    }

    write_audit_record(audit_record)
    return audit_id
```

## Security Governance

### Security Standards

#### Code Security

```python
# Security requirements for code
def validate_security_requirements():
    """Validate code meets security standards."""

    checks = [
        'no_hardcoded_secrets',
        'input_validation',
        'sql_injection_prevention',
        'proper_error_handling',
        'secure_random_generation',
        'dependency_vulnerability_scan'
    ]

    for check in checks:
        if not security_check_passed(check):
            raise SecurityError(f"Security check failed: {check}")
```

#### Access Control

- **Authentication**: Multi-factor authentication required
- **Authorization**: Role-based access control (RBAC)
- **Audit Logging**: All access logged and reviewed
- **Data Encryption**: Encryption at rest and in transit

### Incident Response

#### Incident Classification

```
Severity Levels:
- CRITICAL: Production outage, security breach
- HIGH: Significant functionality loss
- MEDIUM: Partial functionality loss
- LOW: Minor issues, cosmetic problems
```

#### Response Procedures

```python
# Incident response workflow
def incident_response(incident_id: str, severity: str):
    """Execute incident response procedure."""

    # Immediate response
    if severity == 'CRITICAL':
        activate_emergency_response()
        notify_stakeholders(incident_id, severity)
        begin_mitigation(incident_id)

    # Investigation
    root_cause = investigate_incident(incident_id)
    document_findings(incident_id, root_cause)

    # Resolution
    implement_fix(incident_id, root_cause)
    validate_resolution(incident_id)

    # Post-incident
    conduct_retro(incident_id)
    update_procedures(incident_id)
    communicate_resolution(incident_id)
```

## Compliance and Auditing

### Regulatory Compliance

#### Financial Regulations

- **Trade Reporting**: All trades must be reported accurately
- **Risk Management**: Risk limits must be enforced
- **Record Keeping**: Complete audit trail maintained
- **Transparency**: All methodologies documented

#### Data Privacy

- **PII Protection**: No personal information in trading data
- **Data Retention**: Data retained per regulatory requirements
- **Access Controls**: Restricted access to sensitive data
- **Encryption**: Data encrypted at rest and in transit

### Audit Requirements

#### Internal Audits

- **Quarterly Reviews**: Code quality and test coverage
- **Semi-Annual**: Security and performance assessments
- **Annual**: Comprehensive system review

#### External Audits

- **Financial Audit**: Annual financial statement audit
- **Security Audit**: Third-party security assessment
- **Compliance Audit**: Regulatory compliance verification

## Continuous Improvement

### Metrics and Monitoring

#### Key Performance Indicators

```python
# System health metrics
system_metrics = {
    'availability': 'target_99.9%',
    'response_time': 'target_<100ms',
    'error_rate': 'target_<0.1%',
    'test_coverage': 'target_≥80%',
    'deployment_frequency': 'weekly',
    'mttr': 'target_<1hour'
}
```

#### Quality Metrics

- **Defect Density**: Defects per thousand lines of code
- **Test Coverage**: Percentage of code covered by tests
- **Code Review Coverage**: Percentage of code reviewed
- **Documentation Coverage**: Percentage of API documented

### Process Improvement

#### Retrospectives

- **Sprint Retrospectives**: Bi-weekly team retrospectives
- **Release Retrospectives**: Post-release analysis
- **Incident Retrospectives**: Post-incident learning

#### Knowledge Management

- **Documentation**: Comprehensive and up-to-date documentation
- **Training**: Regular team training and knowledge sharing
- **Best Practices**: Documented and shared best practices
- **Innovation**: Encourage experimentation and innovation

This governance framework ensures the QuantStack platform maintains high standards of quality, reliability, and reproducibility while supporting continuous improvement and regulatory compliance.