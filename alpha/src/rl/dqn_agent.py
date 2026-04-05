"""DQN agent for L2 scalping environment."""

import logging
import random
from collections import deque
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

logger = logging.getLogger(__name__)


class QNetwork(nn.Module):
    def __init__(self, obs_dim: int, n_actions: int, hidden: tuple = (128, 64)):
        super().__init__()
        layers = []
        prev = obs_dim
        for h in hidden:
            layers += [nn.Linear(prev, h), nn.ReLU()]
            prev = h
        layers.append(nn.Linear(prev, n_actions))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


class ReplayBuffer:
    def __init__(self, capacity: int = 100_000):
        self.buf = deque(maxlen=capacity)

    def push(self, state, action, reward, next_state, done):
        self.buf.append((state, action, reward, next_state, done))

    def sample(self, batch_size: int):
        batch = random.sample(self.buf, batch_size)
        s, a, r, ns, d = zip(*batch)
        return (
            np.array(s, dtype=np.float32),
            np.array(a, dtype=np.int64),
            np.array(r, dtype=np.float32),
            np.array(ns, dtype=np.float32),
            np.array(d, dtype=np.float32),
        )

    def __len__(self):
        return len(self.buf)


class DQNAgent:
    """Standard DQN with target network and epsilon-greedy exploration."""

    def __init__(
        self,
        obs_dim: int,
        n_actions: int = 3,
        hidden: tuple = (128, 64),
        lr: float = 3e-4,
        gamma: float = 0.99,
        buffer_size: int = 100_000,
        batch_size: int = 64,
        target_update_freq: int = 1000,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay_steps: int = 50_000,
    ):
        self.n_actions = n_actions
        self.gamma = gamma
        self.batch_size = batch_size
        self.target_update_freq = target_update_freq
        self.epsilon_start = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay_steps = epsilon_decay_steps

        self.device = torch.device("cpu")
        self.q_net = QNetwork(obs_dim, n_actions, hidden).to(self.device)
        self.target_net = QNetwork(obs_dim, n_actions, hidden).to(self.device)
        self.target_net.load_state_dict(self.q_net.state_dict())
        self.optimizer = optim.Adam(self.q_net.parameters(), lr=lr)
        self.buffer = ReplayBuffer(buffer_size)
        self.steps = 0

    @property
    def epsilon(self) -> float:
        frac = min(1.0, self.steps / max(1, self.epsilon_decay_steps))
        return self.epsilon_start + frac * (self.epsilon_end - self.epsilon_start)

    def select_action(self, state: np.ndarray, eval_mode: bool = False) -> int:
        if not eval_mode and random.random() < self.epsilon:
            return random.randint(0, self.n_actions - 1)
        with torch.no_grad():
            q = self.q_net(torch.FloatTensor(state).unsqueeze(0).to(self.device))
            return int(q.argmax(dim=1).item())

    def train_step(self) -> Optional[float]:
        if len(self.buffer) < self.batch_size:
            return None

        s, a, r, ns, d = self.buffer.sample(self.batch_size)
        s_t = torch.FloatTensor(s).to(self.device)
        a_t = torch.LongTensor(a).to(self.device)
        r_t = torch.FloatTensor(r).to(self.device)
        ns_t = torch.FloatTensor(ns).to(self.device)
        d_t = torch.FloatTensor(d).to(self.device)

        q_vals = self.q_net(s_t).gather(1, a_t.unsqueeze(1)).squeeze(1)
        with torch.no_grad():
            next_q = self.target_net(ns_t).max(dim=1).values
            target = r_t + self.gamma * next_q * (1 - d_t)

        loss = nn.functional.mse_loss(q_vals, target)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        self.steps += 1
        if self.steps % self.target_update_freq == 0:
            self.target_net.load_state_dict(self.q_net.state_dict())

        return loss.item()

    def train_episode(self, env) -> dict:
        """Run one episode of training. Returns episode stats."""
        obs, _ = env.reset()
        total_reward = 0.0
        steps = 0

        while True:
            action = self.select_action(obs)
            next_obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
            self.buffer.push(obs, action, reward, next_obs, float(done))
            self.train_step()
            total_reward += reward
            obs = next_obs
            steps += 1
            if done:
                break

        return {"reward": total_reward, "steps": steps, "pnl": info.get("total_pnl", 0)}

    def evaluate_episode(self, env) -> dict:
        """Run one episode in eval mode (no exploration, no training)."""
        obs, _ = env.reset()
        total_reward = 0.0
        steps = 0

        while True:
            action = self.select_action(obs, eval_mode=True)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            steps += 1
            if terminated or truncated:
                break

        return {"reward": total_reward, "steps": steps, "pnl": info.get("total_pnl", 0)}
