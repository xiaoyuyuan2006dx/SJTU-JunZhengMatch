"""Read generated MS-SHLLINK data directly, without Windows Script Host path conversion."""
import argparse
import json
import os
from pathlib import Path
import struct


def verify(path,expected_target):
    data=Path(path).read_bytes()
    if len(data)<76 or struct.unpack_from('<I',data)[0]!=76 or data[4:20]!=bytes.fromhex('0114020000000000c000000000000046'):
        raise ValueError('Invalid Shell Link header')
    flags=struct.unpack_from('<I',data,20)[0];offset=76;target=''
    if flags&1:offset+=2+struct.unpack_from('<H',data,offset)[0]
    if flags&2:
        start=offset;size,header_size=struct.unpack_from('<II',data,start)
        if size<28 or start+size>len(data):raise ValueError('Invalid LinkInfo size')
        unicode_offset=struct.unpack_from('<I',data,start+28)[0] if header_size>=36 else 0
        if unicode_offset:
            pos=start+unicode_offset;end=pos
            while end+2<=start+size and data[end:end+2]!=b'\0\0':end+=2
            target=data[pos:end].decode('utf-16le')
        else:
            base=struct.unpack_from('<I',data,start+16)[0]
            if base:target=data[start+base:start+size].split(b'\0',1)[0].decode('mbcs' if os.name=='nt' else 'utf-8')
        offset+=size
    strings={}
    for bit,name in [(4,'name'),(8,'relative'),(16,'working'),(32,'arguments'),(64,'icon')]:
        if not flags&bit:continue
        length=struct.unpack_from('<H',data,offset)[0];offset+=2
        size=length*(2 if flags&128 else 1)
        if offset+size>len(data):raise ValueError('Truncated shortcut string')
        strings[name]=data[offset:offset+size].decode('utf-16le' if flags&128 else 'ascii');offset+=size
    if strings.get('arguments')!='--desktop':raise ValueError('Shortcut arguments mismatch: '+repr(strings))
    if os.path.normcase(os.path.normpath(target))!=os.path.normcase(os.path.normpath(expected_target)):
        raise ValueError('Shortcut target mismatch: '+repr(target))
    return dict(status='ok',desktop_arguments=True,target_matches=True,valid_shell_link=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--path',required=True);parser.add_argument('--expected-target',required=True);args=parser.parse_args()
    print(json.dumps(verify(args.path,args.expected_target)))
