"""Gym-compatible L2 scalping environment.

State: ML feature vector + position state.
Actions: hold(0), go_long(1), go_short(2).
Reward: realized PnL on exit minus costs, with optional holding penalty.
"""

import logging
from typing import Optional

import gymnasium as gym
import numpy as np
from gymnasium import spaces

logger = logging.getLogger(__name__)


class L2ScalpingEnv(gym.Env):
    """OpenAI Gym environment for L2 order book scalping."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        features: np.ndarray,
        mids: np.ndarray,
        spreads: np.ndarray,
        commission_per_share: float = 0.005,
        holding_penalty: float = 0.0001,
        reward_type: str = "shaped",
        max_steps: Optional[int] = None,
    ):
        """
        Args:
            features: (T, n_features) array of ML features for one episode.
            mids: (T,) mid prices.
            spreads: (T,) bid-ask spreads.
            commission_per_share: Commission cost.
            holding_penalty: Per-step penalty while in position.
            reward_type: 'sparse', 'dense', or 'shaped'.
            max_steps: Max steps per episode (None = use full data).
        """
        super().__init__()
        self.features = features.astype(np.float32)
        self.mids = mids.astype(np.float64)
        self.spreads = spreads.astype(np.float64)
        self.commission = commission_per_share
        self.holding_penalty = holding_penalty
        self.reward_type = reward_type
        self.max_steps = max_steps or len(features)

        n_feat = features.shape[1]
        # Observation: features + [position_side, unrealized_pnl, hold_steps]
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(n_feat + 3,),
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(3)  # 0=hold, 1=long, 2=short

        self._step = 0
        self._position = 0  # 0=flat, 1=long, -1=short
        self._entry_price = 0.0
        self._hold_steps = 0
        self._total_pnl = 0.0

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self._step = 0
        self._position = 0
        self._entry_price = 0.0
        self._hold_steps = 0
        self._total_pnl = 0.0
        return self._obs(), {}

    def step(self, action: int):
        mid = self.mids[self._step]
        half_spread = self.spreads[self._step] / 2
        reward = 0.0
        realized = 0.0

        if self._position == 0:
            # Flat — can enter
            if action == 1:  # go long
                self._position = 1
                self._entry_price = mid + half_spread  # buy at ask
                self._hold_steps = 0
            elif action == 2:  # go short
                self._position = -1
                self._entry_price = mid - half_spread  # sell at bid
                self._hold_steps = 0
        else:
            # In position — action 0 = hold, 1 or 2 = exit
            if action != 0:
                # Exit
                if self._position == 1:
                    exit_price = mid - half_spread  # sell at bid
                    realized = exit_price - self._entry_price
                else:
                    exit_price = mid + half_spread  # buy at ask
                    realized = self._entry_price - exit_price
                realized -= self.commission * 2  # round-trip commission (per share)
                self._total_pnl += realized
                self._position = 0
                self._entry_price = 0.0
            else:
                self._hold_steps += 1

        # Compute reward based on type
        if self.reward_type == "sparse":
            reward = realized
        elif self.reward_type == "dense":
            if self._position != 0:
                unrealized = self._unrealized_pnl(mid)
                reward = unrealized - self.holding_penalty
            else:
                reward = realized
        else:  # shaped
            reward = realized
            if realized > 0:
                reward += 0.001  # bonus for profitable exit
            if self._position != 0:
                reward -= self.holding_penalty

        self._step += 1
        terminated = self._step >= min(self.max_steps, len(self.features))
        truncated = False

        # Force close at end
        if terminated and self._position != 0:
            if self._position == 1:
                exit_price = mid - half_spread
                forced_pnl = exit_price - self._entry_price - self.commission * 2
            else:
                exit_price = mid + half_spread
                forced_pnl = self._entry_price - exit_price - self.commission * 2
            reward += forced_pnl
            self._total_pnl += forced_pnl
            self._position = 0

        obs = (
            self._obs()
            if not terminated
            else np.zeros(self.observation_space.shape, dtype=np.float32)
        )
        return obs, float(reward), terminated, truncated, {"total_pnl": self._total_pnl}

    def _obs(self) -> np.ndarray:
        idx = min(self._step, len(self.features) - 1)
        feat = self.features[idx]
        pos_state = np.array(
            [
                float(self._position),
                self._unrealized_pnl(self.mids[idx]),
                float(self._hold_steps),
            ],
            dtype=np.float32,
        )
        return np.concatenate([feat, pos_state])

    def _unrealized_pnl(self, mid: float) -> float:
        if self._position == 0:
            return 0.0
        half_spread = self.spreads[min(self._step, len(self.spreads) - 1)] / 2
        if self._position == 1:
            return (mid - half_spread) - self._entry_price
        return self._entry_price - (mid + half_spread)
