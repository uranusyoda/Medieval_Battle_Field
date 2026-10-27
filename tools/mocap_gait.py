"""Periodic, denoised locomotion from CMU Subject 35 endpoint trajectories.

The Fourier fit is periodic in position AND velocity, unlike setting just the
first and last authored poses equal. Character proportions are kept by the
retargeter; captured bone directions supply human coordination.
"""
from pathlib import Path
import numpy as np
from cmu_motion import load_motion

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'assets/mocap/cmu'


def design(t, harmonics):
    t = np.atleast_1d(t)
    return np.column_stack([np.ones(len(t))]+[
        f(2*np.pi*k*t) for k in range(1, harmonics+1) for f in (np.cos, np.sin)])


class Gait:
    def __init__(self, running=False):
        self.running = running
        self.motion = load_motion(DATA/'35.asf', DATA/('35_18.amc' if running else '35_01.amc'))
        m = self.motion
        center = (m.positions['lhipjoint']+m.positions['rhipjoint'])/2
        self.names = list(m.positions)
        positions = np.stack([m.positions[n]-center for n in self.names], axis=1)
        # Use both body pose and velocity to locate a repeating, steady stride.
        features = np.concatenate([positions[:, self.names.index(n)] for n in
            ('lfemur','rfemur','ltibia','rtibia','lfoot','rfoot','lhumerus','rhumerus','lradius','rradius')], axis=1)
        velocity = np.gradient(features, axis=0)*m.fps
        limits = (.55, .90) if running else (.85, 1.35)
        best = None
        for start in range(8, len(m)-int(limits[0]*m.fps)-8):
            for length in range(round(limits[0]*m.fps), round(limits[1]*m.fps)+1):
                end = start+length
                if end >= len(m)-5:
                    continue
                pose_error = np.sqrt(np.mean((features[start]-features[end])**2))
                velocity_error = np.sqrt(np.mean((velocity[start]-velocity[end])**2))
                score = pose_error+.025*velocity_error
                if best is None or score < best[0]:
                    best = (score, start, end, pose_error, velocity_error)
        assert best is not None
        score, start, end, pose_error, velocity_error = best
        self.start, self.end = start, end
        self.duration = (end-start)/m.fps
        self.harmonics = 7 if running else 8
        t = np.linspace(0, 1, end-start+1)
        x = design(t, self.harmonics)
        reg = np.diag([0.]+[.004*(k/self.harmonics)**4 for k in range(1,self.harmonics+1) for _ in range(2)])
        values = positions[start:end+1].reshape(len(t), -1)
        self.coefficients = np.linalg.solve(x.T@x+reg, x.T@values)
        pelvis = center[start:end+1].copy()
        pelvis[:, :2] -= np.linspace(pelvis[0, :2], pelvis[-1, :2], len(t))
        pelvis[:, 2] -= pelvis[:, 2].mean()
        self.pelvis_coefficients = np.linalg.solve(x.T@x+reg, x.T@pelvis)
        source_lengths = [np.linalg.norm(m.positions[s+'femur'][start]-m.positions[s+'hipjoint'][start])+
                          np.linalg.norm(m.positions[s+'tibia'][start]-m.positions[s+'femur'][start]) for s in ('l','r')]
        self.source_leg_length = float(np.mean(source_lengths))
        # Captured toe/foot endpoints locate flight without forcing every run
        # frame down to the floor. Hands/feet noisy DOFs are not copied.
        samples = [self.sample(float(q)) for q in np.linspace(0, 1, 241)]
        low = np.array([min(s[n][2] for n in ('lfoot','rfoot','ltoes','rtoes')) for s in samples])
        self.floor_reference = float(np.quantile(low, .10))
        self.info = dict(source='CMU Subject 35', take='35_18' if running else '35_01',
            raw_fps=m.fps, source_start=start, source_end=end,
            stride_duration=self.duration, period_fit_harmonics=self.harmonics,
            matching_pose_rms_m=float(pose_error), matching_velocity_rms_m_s=float(velocity_error),
            source_leg_length_m=self.source_leg_length,
            minimum_step_width_m=float(np.min([abs(s['ltibia'][0]-s['rtibia'][0]) for s in samples])),
            mean_step_width_m=float(np.mean([abs(s['ltibia'][0]-s['rtibia'][0]) for s in samples])))

    def sample(self, phase):
        row = design(float(phase)%1, self.harmonics)[0]
        values = (row@self.coefficients).reshape(len(self.names), 3)
        return {n: p for n,p in zip(self.names, values)}

    def pelvis(self, phase):
        return design(float(phase)%1, self.harmonics)[0]@self.pelvis_coefficients

    def flight(self, phase):
        if not self.running:
            return 0.
        p = self.sample(phase)
        low = min(p[n][2] for n in ('lfoot','rfoot','ltoes','rtoes'))
        return max(0., float(low-self.floor_reference))


if __name__ == '__main__':
    import json
    for run in (False, True):
        print(json.dumps(Gait(run).info, indent=2))
