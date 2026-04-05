"""Baseline agents for RL comparison: random, rule-based, and ML policy wrappers."""

import numpy as np


class RandomAgent:
    """Uniformly random action selection."""

    def __init__(self, n_actions: int = 3):
        self.n_actions = n_actions

    def select_action(self, obs: np.ndarray, **kwargs) -> int:
        return np.random.randint(0, self.n_actions)

    def evaluate_episode(self, env) -> dict:
        obs, _ = env.reset()
        total_reward = 0.0
        steps = 0
        while True:
            action = self.select_action(obs)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            steps += 1
            if terminated or truncated:
                break
        return {"reward": total_reward, "steps": steps, "pnl": info.get("total_pnl", 0)}


class RuleBasedAgent:
    """Wraps a simple OBI threshold rule as an RL policy.

    Goes long when obi_1 > threshold, short when obi_1 < -threshold.
    obi_1 is assumed to be at feature index `obi_idx` in the observation.
    """

    def __init__(self, obi_idx: int = 0, threshold: float = 0.3):
        self.obi_idx = obi_idx
        self.threshold = threshold

    def select_action(self, obs: np.ndarray, **kwargs) -> int:
        obi = obs[self.obi_idx]
        position = obs[-3]  # position_side is 3rd from end in L2ScalpingEnv obs
        if position == 0:
            if obi > self.threshold:
                return 1  # long
            elif obi < -self.threshold:
                return 2  # short
            return 0  # hold
        else:
            if position == 1 and obi < -self.threshold:
                return 2  # exit long
            if position == -1 and obi > self.threshold:
                return 1  # exit short
            return 0  # hold

    def evaluate_episode(self, env) -> dict:
        obs, _ = env.reset()
        total_reward = 0.0
        steps = 0
        while True:
            action = self.select_action(obs)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            steps += 1
            if terminated or truncated:
                break
        return {"reward": total_reward, "steps": steps, "pnl": info.get("total_pnl", 0)}


class MLPolicyAgent:
    """Wraps a trained XGBoost model as an RL policy."""

    def __init__(self, model, n_features: int, threshold: float = 0.55):
        self.model = model
        self.n_features = n_features
        self.threshold = threshold

    def select_action(self, obs: np.ndarray, **kwargs) -> int:
        position = obs[-3]
        feat = obs[: self.n_features].reshape(1, -1)
        feat = np.nan_to_num(feat, nan=0.0, posinf=0.0, neginf=0.0)
        proba = self.model.predict_proba(feat)[0]
        p_down, p_flat, p_up = proba

        if position == 0:
            if p_up > self.threshold and p_up > p_down:
                return 1
            if p_down > self.threshold and p_down > p_up:
                return 2
            return 0
        else:
            if position == 1 and p_down > self.threshold:
                return 2
            if position == -1 and p_up > self.threshold:
                return 1
            return 0

    def evaluate_episode(self, env) -> dict:
        obs, _ = env.reset()
        total_reward = 0.0
        steps = 0
        while True:
            action = self.select_action(obs)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            steps += 1
            if terminated or truncated:
                break
        return {"reward": total_reward, "steps": steps, "pnl": info.get("total_pnl", 0)}
