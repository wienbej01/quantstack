"""Tests for Sprint 5: RL Environment and Agents."""

import numpy as np
import pytest

from src.rl.l2_env import L2ScalpingEnv
from src.rl.dqn_agent import DQNAgent, ReplayBuffer
from src.rl.baselines import RandomAgent, RuleBasedAgent


def _make_env(n: int = 200, reward_type: str = "shaped") -> L2ScalpingEnv:
    rng = np.random.RandomState(42)
    n_feat = 5
    features = rng.randn(n, n_feat).astype(np.float32)
    mids = 50.0 + np.cumsum(rng.randn(n) * 0.01)
    spreads = np.full(n, 0.02)
    return L2ScalpingEnv(features, mids, spreads, reward_type=reward_type)


class TestL2ScalpingEnv:
    def test_reset_returns_correct_shape(self):
        env = _make_env()
        obs, info = env.reset()
        assert obs.shape == env.observation_space.shape

    def test_step_returns_correct_types(self):
        env = _make_env()
        env.reset()
        obs, reward, terminated, truncated, info = env.step(0)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(info, dict)

    def test_episode_terminates(self):
        env = _make_env(n=50)
        env.reset()
        done = False
        steps = 0
        while not done:
            _, _, terminated, truncated, _ = env.step(0)
            done = terminated or truncated
            steps += 1
        assert steps == 50

    def test_long_trade_pnl(self):
        # Constant rising mid: long should profit
        n = 20
        features = np.zeros((n, 3), dtype=np.float32)
        mids = np.linspace(50.0, 51.0, n)  # rising
        spreads = np.full(n, 0.02)
        env = L2ScalpingEnv(
            features, mids, spreads, commission_per_share=0, reward_type="sparse"
        )
        env.reset()
        env.step(1)  # go long at step 0
        for _ in range(n - 2):
            env.step(0)  # hold
        _, reward, _, _, info = env.step(1)  # exit at last step
        assert info["total_pnl"] > 0

    def test_flat_no_pnl(self):
        env = _make_env(n=50)
        env.reset()
        for _ in range(50):
            _, _, terminated, _, info = env.step(0)
            if terminated:
                break
        assert info["total_pnl"] == 0.0

    def test_all_reward_types(self):
        for rt in ("sparse", "dense", "shaped"):
            env = _make_env(reward_type=rt)
            env.reset()
            env.step(1)  # enter
            _, reward, _, _, _ = env.step(0)  # hold
            assert isinstance(reward, float)


class TestDQNAgent:
    def test_select_action_valid(self):
        agent = DQNAgent(obs_dim=8, n_actions=3)
        obs = np.random.randn(8).astype(np.float32)
        action = agent.select_action(obs)
        assert action in (0, 1, 2)

    def test_eval_mode_deterministic(self):
        agent = DQNAgent(obs_dim=8, n_actions=3)
        obs = np.random.randn(8).astype(np.float32)
        a1 = agent.select_action(obs, eval_mode=True)
        a2 = agent.select_action(obs, eval_mode=True)
        assert a1 == a2  # deterministic in eval

    def test_train_episode_runs(self):
        env = _make_env(n=50)
        agent = DQNAgent(obs_dim=env.observation_space.shape[0], batch_size=8)
        result = agent.train_episode(env)
        assert "reward" in result
        assert "pnl" in result

    def test_epsilon_decays(self):
        agent = DQNAgent(
            obs_dim=8, epsilon_start=1.0, epsilon_end=0.05, epsilon_decay_steps=100
        )
        assert agent.epsilon == 1.0
        agent.steps = 50
        assert agent.epsilon < 1.0
        agent.steps = 100
        assert agent.epsilon == pytest.approx(0.05)


class TestReplayBuffer:
    def test_push_and_sample(self):
        buf = ReplayBuffer(capacity=100)
        for i in range(20):
            buf.push(np.zeros(4), 0, 1.0, np.zeros(4), False)
        assert len(buf) == 20
        s, a, r, ns, d = buf.sample(5)
        assert s.shape == (5, 4)


class TestBaselines:
    def test_random_agent_runs(self):
        env = _make_env(n=50)
        agent = RandomAgent()
        result = agent.evaluate_episode(env)
        assert "pnl" in result

    def test_rule_based_agent_runs(self):
        env = _make_env(n=50)
        agent = RuleBasedAgent(obi_idx=0)
        result = agent.evaluate_episode(env)
        assert "pnl" in result
