"""Constant-velocity Kalman filter with analytic 2x2 innovation inverse.

State [x, y, vx, vy]; position in pixels and velocity in pixels/second.
Uses basic NumPy arithmetic only, no numpy.linalg. Joseph covariance update
preserves numerical symmetry and positive semidefiniteness under roundoff.
While coasting, predict(damping > 0) lets velocity decay as exp(-damping*t).
"""
import numpy as np


class KalmanFilter:
    def __init__(self, x, y, acceleration_noise=800., measurement_noise=4.):
        # acceleration_noise: px/s^2 (std). measurement_noise: px^2 (variance).
        self.state = np.array([x, y, 0., 0.], dtype=float)
        self.covariance = np.diag([16., 16., 10000., 10000.])
        self.acceleration_noise = acceleration_noise
        self.measurement_noise = measurement_noise

    def predict(self, dt, damping=0.):
        if not np.isfinite(dt) or dt <= 0:
            raise ValueError('dt must be finite and positive')
        decay = np.exp(-damping*dt)
        carry = dt if damping == 0 else (1-decay)/damping  # exact position integral
        transition = np.eye(4)
        transition[0, 2] = transition[1, 3] = carry
        transition[2, 2] = transition[3, 3] = decay
        drive = np.array([[dt*dt/2, 0], [0, dt*dt/2], [dt, 0], [0, dt]])
        self.state = transition @ self.state
        self.covariance = transition @ self.covariance @ transition.T + self.acceleration_noise**2 * (drive @ drive.T)
        return self.state[:2].copy()

    def innovation(self, measurement, r=None):
        r = self.measurement_noise if r is None else r
        residual = np.asarray(measurement, dtype=float) - self.state[:2]
        s = self.covariance[:2, :2] + np.eye(2)*r
        a, b, c, d = s.ravel()
        determinant = a*d-b*c
        if determinant <= 1e-12:
            raise ArithmeticError('Singular innovation covariance')
        inverse = np.array([[d, -b], [-c, a]]) / determinant
        return residual, inverse, float(residual @ inverse @ residual)

    def update(self, measurement, gate=100., r=None):
        """r overrides the measurement variance for this update (weak matches get a larger r)."""
        r = self.measurement_noise if r is None else r
        residual, inverse, distance = self.innovation(measurement, r)
        if distance > gate:
            return False
        gain = self.covariance[:, :2] @ inverse
        self.state += gain @ residual
        a = np.eye(4)
        a[:, :2] -= gain
        self.covariance = a @ self.covariance @ a.T + r * gain @ gain.T
        self.covariance = (self.covariance + self.covariance.T) / 2
        return True

    def reacquire(self, measurement):
        """Hard reset onto a trusted measurement after the filter has diverged."""
        self.state = np.array([*measurement, 0., 0.], dtype=float)
        self.covariance = np.diag([self.measurement_noise, self.measurement_noise, 10000., 10000.])

    def stop(self):
        """Forget velocity (used when the track is declared LOST)."""
        self.state[2:] = 0.
        self.covariance[2:, :] = 0.
        self.covariance[:, 2:] = 0.
        self.covariance[2, 2] = self.covariance[3, 3] = 10000.
