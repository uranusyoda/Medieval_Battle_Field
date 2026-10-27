"""A compact, staggered stealth crouch for the anatomical knight.

Three-second looping study: step into a guarded low stance, breathe, rise and
collect the feet. The stance is fore/aft, not a wide lateral horse stance.
"""
import math
from mathutils import Vector, Quaternion


def _ease(x):
    x=max(0.,min(1.,x))
    return x*x*(3-2*x)


def crouch_sample(normalized):
    t=0. if normalized==1. else max(0.,min(1.,normalized))
    down=_ease((t-.08)/.26)
    up=_ease((t-.68)/.28)
    q=down*(1-up)
    left_in=_ease((t-.015)/.175)
    left_out=_ease((t-.82)/.16)
    right_in=_ease((t-.19)/.13)
    right_out=_ease((t-.69)/.13)
    return dict(t=t,q=q,breath=math.sin(math.tau*t),
                left=left_in*(1-left_out),right=right_in*(1-right_out),
                left_lift=.034*(math.sin(math.pi*left_in)*(1-left_out)+math.sin(math.pi*left_out)),
                right_lift=.042*(math.sin(math.pi*right_in)*(1-right_out)+math.sin(math.pi*right_out)))


def _blend(a,b,t):
    return Vector(a).lerp(Vector(b),t).normalized()


def solve_ninja_crouch(arm,normalized,Pose,ik_leg,fingers):
    s=crouch_sample(normalized);q=s['q'];breath=s['breath']
    p=Pose(arm);p.local('root')
    # Load the front leg while preserving a usable trailing leg, rather than
    # settling symmetrically onto both heels like an exercise squat.
    p.local('hips',Quaternion((0,0,1),math.radians(-3.5*q)),
            (.025*q,-.050*q,-.012-.343*q+.0025*q*breath))
    p.aim('spine',(.016*q,-.54*q,1))
    p.aim('chest',(.025*q,.035-.855*q+.006*q*breath,1))
    p.aim('neck',(.004*q,.010-.110*q,1))
    p.aim('head',(.002*q,.004-.074*q,1))
    for side,sign in [('L',1),('R',-1)]:
        p.aim(f'shoulder.{side}',(sign*.20,.022,.014+.006*q))
        neutral_up=(sign*.375,.020,-.927)
        neutral_fore=(sign*.31,-.13,-1)
        if side=='L':
            # Lead hand probes ahead below the sternum, with a soft elbow.
            upper=_blend(neutral_up,(.43,-.30,-.85),q)
            fore=_blend(neutral_fore,(.25,-.94,.22),q)
            step=s['left'];lift=s['left_lift']
            ankle=(.18-.025*step,.079-.210*step,.09+lift)
            pitch=0.
        else:
            # The rear hand stays beside and behind the hip; it is not a
            # second outstretched balancing arm.
            upper=_blend(neutral_up,(-.47,.25,-.846),q)
            fore=_blend(neutral_fore,(-.25,.65,-.72),q)
            step=s['right'];lift=s['right_lift']
            ankle=(-.18+.025*step,.104+.208*step,.09+.068*q+lift)
            pitch=24*q
        p.aim(f'upper_arm.{side}',upper)
        p.aim(f'forearm.{side}',fore)
        p.aim(f'hand.{side}',fore,(sign,.08,0))
        p.world(f'hand.{side}',p.rot[f'hand.{side}']@
                Quaternion((1,0,0),-math.radians(4+3*q)).to_matrix())
        fingers(p,side,.34+.08*q,spread=-4.,relaxed=True)
        ik_leg(p,side,ankle,pitch)
    p.finish()
    return 0.
