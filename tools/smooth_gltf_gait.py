"""Give baked idle/walk/run channels cyclic tangents for seamless velocity.

glTF LINEAR samples match endpoint positions but their slopes still jump at
the loop. CUBICSPLINE stores matching endpoint tangents explicitly; Three's
glTF loader also normalizes the interpolated quaternion channels.
"""
from pathlib import Path
import json
import struct
import numpy as np
from patch_anatomical_glb import read_glb, accessor


def smooth(path):
    path = Path(path)
    doc, raw = read_glb(path)
    binary = bytearray(raw)
    converted = 0
    def append(data, typ):
        data = np.ascontiguousarray(data, dtype='<f4')
        while len(binary)%4:
            binary.append(0)
        view = len(doc['bufferViews'])
        doc['bufferViews'].append(dict(buffer=0,byteOffset=len(binary),byteLength=data.nbytes))
        binary.extend(data.tobytes())
        index = len(doc['accessors'])
        doc['accessors'].append(dict(bufferView=view,componentType=5126,count=len(data),type=typ))
        return index
    for animation in doc.get('animations',[]):
        if animation['name'] not in ('idle','walk','run'):
            continue
        kinds = {c['sampler']:c['target']['path'] for c in animation['channels']}
        for index,sampler in enumerate(animation['samplers']):
            if sampler.get('interpolation','LINEAR') != 'LINEAR':
                continue
            times = accessor(doc,raw,sampler['input']).ravel().astype(float)
            values = accessor(doc,raw,sampler['output']).astype(float)
            if len(times)<2:
                continue
            rotation = kinds[index]=='rotation'
            if rotation:
                for j in range(1,len(values)):
                    if np.dot(values[j-1],values[j]) < 0:
                        values[j] *= -1
                assert np.dot(values[0],values[-1]) > .9999
            assert np.max(np.abs(values[0]-values[-1])) < .0002
            values[-1] = values[0]
            tangent = np.zeros_like(values)
            if len(times)>2:
                tangent[1:-1] = (values[2:]-values[:-2])/(times[2:]-times[:-2])[:,None]
                tangent[0] = (values[1]-values[-2])/(times[1]-(times[-2]-(times[-1]-times[0])))
                tangent[-1] = tangent[0]
            if rotation:
                tangent -= values*np.sum(values*tangent,axis=1)[:,None]
            cubic = np.stack([tangent,values,tangent],axis=1).reshape(-1,values.shape[1])
            sampler['output'] = append(cubic,'VEC4' if rotation else 'VEC3')
            sampler['interpolation'] = 'CUBICSPLINE'
            converted += 1
    while len(binary)%4:
        binary.append(0)
    doc['buffers'][0]['byteLength'] = len(binary)
    data=json.dumps(doc,ensure_ascii=False,separators=(',',':')).encode('utf8')
    data+=b' '*(-len(data)%4)
    result=struct.pack('<4sII',b'glTF',2,28+len(data)+len(binary))
    result+=struct.pack('<II',len(data),0x4E4F534A)+data
    result+=struct.pack('<II',len(binary),0x004E4942)+binary
    path.write_bytes(result)
    return converted


if __name__=='__main__':
    import sys
    print('CUBIC_GAIT_CHANNELS',smooth(sys.argv[1]))
