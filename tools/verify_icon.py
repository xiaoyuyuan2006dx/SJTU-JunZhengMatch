"""Verify that the built Windows PE contains every image from the selected ICO."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def verify(executable,icon):
    import pefile
    data=Path(icon).read_bytes()
    reserved,kind,count=struct.unpack_from('<HHH',data)
    if (reserved,kind)!=(0,1) or not count:raise ValueError('Invalid ICO file')
    expected=set();sizes=[]
    for index in range(count):
        width,height,_,_,_,_,size,offset=struct.unpack_from('<BBBBHHII',data,6+16*index)
        payload=data[offset:offset+size]
        if len(payload)!=size:raise ValueError('Truncated ICO image')
        sizes.append([width or 256,height or 256])
        expected.add(hashlib.sha256(payload).hexdigest())
    actual=set()
    with pefile.PE(str(executable)) as pe:
        for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if entry.id!=3:continue  # RT_ICON
            for image in entry.directory.entries:
                for language in image.directory.entries:
                    resource=language.data.struct
                    payload=pe.get_data(resource.OffsetToData,resource.Size)
                    actual.add(hashlib.sha256(payload).hexdigest())
    if not expected.issubset(actual):raise ValueError('EXE icon resources do not match the selected ICO')
    return dict(status='ok',embedded_images=count,sizes=sizes,exact_icon_payloads=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--exe',required=True);parser.add_argument('--icon',default='assets/app.ico');parser.add_argument('--report')
    args=parser.parse_args();result=verify(args.exe,args.icon)
    if args.report:Path(args.report).write_text(json.dumps(result),encoding='utf-8')
    print(json.dumps(result))
