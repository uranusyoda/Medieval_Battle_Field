"""Athletic in-place jump, authored for the anatomical knight (metres, seconds).

The hips follow a ballistic trajectory in flight. Sole grounding is frozen in
flight so pulling the knees up does not translate the whole character.
"""
import math
from mathutils import Vector, Quaternion

TAKEOFF = .45
LANDING = 1.10
DURATION = 2.0
GRAVITY = 9.81


def _smooth(x):
    x = max(0., min(1., x))
    return x*x*(3-2*x)


def _curve(t, keys):
    """Cubic Hermite with finite shared tangents (no pauses at every pose)."""
    if t <= keys[0][0]:
        return float(keys[0][1])
    if t >= keys[-1][0]:
        return float(keys[-1][1])
    slopes = [0.]
    for i in range(1,len(keys)-1):
        a,b,c=keys[i-1],keys[i],keys[i+1]
        l=(b[1]-a[1])/(b[0]-a[0]); r=(c[1]-b[1])/(c[0]-b[0])
        # Shape-preserving weighted harmonic tangent at monotonic knots.
        if l*r <= 0:
            slopes.append(0.)
        else:
            h0,h1=b[0]-a[0],c[0]-b[0]
            w0,w1=2*h1+h0,h1+2*h0
            slopes.append((w0+w1)/(w0/l+w1/r))
    slopes.append(0.)
    for i,((a,x),(b,y)) in enumerate(zip(keys,keys[1:])):
        if t<=b:
            u=(t-a)/(b-a); h=b-a
            return ((2*u**3-3*u*u+1)*x+(u**3-2*u*u+u)*h*slopes[i]
                    +(-2*u**3+3*u*u)*y+(u**3-u*u)*h*slopes[i+1])
    return float(keys[-1][1])


def _hermite(t, a, b, x, y, dx, dy):
    u=max(0.,min(1.,(t-a)/(b-a)));h=b-a
    return ((2*u**3-3*u*u+1)*x+(u**3-2*u*u+u)*h*dx
            +(-2*u**3+3*u*u)*y+(u**3-u*u)*h*dy)


def jump_sample(seconds):
    t=max(0.,min(DURATION,seconds))
    flight=TAKEOFF<t<LANDING
    u=max(0.,min(1.,(t-TAKEOFF)/(LANDING-TAKEOFF)))
    lift=.5*GRAVITY*(LANDING-TAKEOFF)**2*u*(1-u)
    hip=_curve(t,[(0,-.012),(.08,-.012),(.30,-.235),(.32,-.25),
                       (TAKEOFF,.048),(LANDING,.020),(1.23,-.215),
                       (1.50,-.035),(1.67,-.006),(2,-.012)])
    velocity=.5*GRAVITY*(LANDING-TAKEOFF)-.028/(LANDING-TAKEOFF)
    if .32<t<TAKEOFF:
        hip=_hermite(t,.32,TAKEOFF,-.25,.048,0.,velocity)
    elif LANDING<t<1.23:
        hip=_hermite(t,LANDING,1.23,.020,-.215,
                     -(.5*GRAVITY*(LANDING-TAKEOFF)+.028/(LANDING-TAKEOFF)),0.)
    # The ascent and descent are one unbroken parabola, rather than a set of
    # individually eased poses. The small height difference at contact is part of the same parabola.
    if TAKEOFF<=t<=LANDING:
        hip=.048-.028*u+lift
    lean=_curve(t,[(0,.015),(.12,.08),(.34,.38),(TAKEOFF,.105),
                  (.72,-.015),(.93,.05),(LANDING,.18),(1.235,.32),
                  (1.53,.055),(2,.015)])
    hip_y=_curve(t,[(0,0),(.34,.092),(TAKEOFF,-.012),(.72,-.005),
                   (LANDING,.018),(1.235,.074),(1.53,.012),(2,0)])
    elevation=_curve(t,[(0,3),(.12,-5),(.31,-34),(.36,-28),
                       (TAKEOFF,54),(.56,82),(.77,62),(.99,32),
                       (LANDING,30),(1.235,44),(1.52,10),(2,3)])
    elbow=_curve(t,[(0,19),(.31,25),(.36,32),(TAKEOFF,54),
                   (.60,65),(.79,68),(LANDING,38),(1.235,35),(1.60,22),(2,19)])
    tuck=_curve(t,[(0,0),(TAKEOFF,0),(.62,.75),(.77,1),(.94,.48),
                  (1.05,.10),(LANDING,0),(2,0)])
    heel=_curve(t,[(0,0),(.34,0),(TAKEOFF,1),(.59,.90),(.87,.60),
                  (LANDING,.32),(1.18,0),(2,0)])
    return dict(t=t,airborne=flight,lift=lift,hip_z=hip,hip_y=hip_y,
                lean=lean,elevation=elevation,elbow=elbow,tuck=tuck,heel=heel,
                flight_phase=u)


def _arm_direction(sign, elevation, abduction):
    a=math.radians(elevation)
    side=math.sin(math.radians(abduction))
    axial=math.cos(math.radians(abduction))
    return Vector((sign*side,-math.sin(a)*axial,-math.cos(a)*axial))


def solve_athletic_jump(arm, seconds, Pose, ik_leg, fingers):
    """Apply the complete jump pose; return nominal airborne sole elevation."""
    s=jump_sample(seconds); t=s['t']; u=s['flight_phase']
    p=Pose(arm);p.local('root')
    asym=math.sin(math.pi*u)**2 if s['airborne'] else 0.
    p.local('hips',Quaternion((0,0,1),math.radians(1.3*asym)),
            (.004*asym,s['hip_y'],s['hip_z']))
    p.aim('spine',(0,-s['lean']*.42,1))
    p.aim('chest',(0,-s['lean'],1))
    p.aim('neck',(0,-.02-.12*s['lean'],1))
    p.aim('head',(0,-.02,1))
    for side,sign in [('L',1),('R',-1)]:
        # A small lag between the arms avoids a synchronized exercise pose.
        arm_s=jump_sample(t-(.014 if side=='R' else 0))
        abduction=15+5*asym+2*_smooth((t-.95)/.15)*(1-_smooth((t-1.35)/.3))
        p.aim(f'shoulder.{side}',(sign*.15,.036,.015+ .012*asym))
        upper=_arm_direction(sign,arm_s['elevation'],abduction)
        # Preserve a real forward elbow hinge, instead of using two nearly
        # parallel rods. Forearms follow the accelerated upper arms.
        bend=math.radians(arm_s['elbow']+(2 if side=='R' else 0)*asym)
        forward=Vector((0,-math.cos(math.radians(arm_s['elevation'])),
                        math.sin(math.radians(arm_s['elevation']))))
        forward=(forward-upper*forward.dot(upper)).normalized()
        fore=upper*math.cos(bend)+forward*math.sin(bend)
        p.aim(f'upper_arm.{side}',upper)
        p.aim(f'forearm.{side}',fore)
        p.aim(f'hand.{side}',fore,(sign,.10,0))
        p.world(f'hand.{side}',p.rot[f'hand.{side}']@
                Quaternion((1,0,0),-math.radians(3+4*asym)).to_matrix())
        fingers(p,side,.33+.10*asym,spread=-4.,relaxed=True)
        # Feet stay under the hips, then fold up a little behind them. The
        # leading knee lifts farther; the trailing leg follows, 20 ms later.
        leg_s=jump_sample(t-(.020 if side=='R' else 0))
        tuck=leg_s['tuck']; heel=s['heel']
        height=.09+.060*heel+s['lift']+tuck*(.19 if side=='L' else .145)
        ankle_y=.079+.095*tuck+(sign*.022*asym)
        ankle_x=sign*(.16+.012*asym)
        pitch=26*heel-8*tuck
        ik_leg(p,side,(ankle_x,ankle_y,height),pitch)
    p.finish()
    return s['lift']


def jump_grounding(seconds, raw_floor, state):
    """Sole contact on the ground, constant root correction through flight.

    The final 50 ms blends to the predicted contact offset, removing the
    tiny boot-shape discrepancy between plantar flexion and first contact.
    Subtracting ballistic lift from raw_floor retains descending speed.
    """
    s=jump_sample(seconds);t=s['t']
    if t<=TAKEOFF:
        correction=-raw_floor
        state['takeoff_correction']=correction
    elif t<LANDING:
        frozen=state.get('takeoff_correction',-raw_floor+s['lift'])
        contact=-raw_floor+s['lift']
        blend=_smooth((t-(LANDING-.05))/.05)
        correction=frozen*(1-blend)+contact*blend
    else:
        correction=-raw_floor
    return correction
