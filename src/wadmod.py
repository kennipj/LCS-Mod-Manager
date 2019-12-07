#!/bin/env python3
import shutil
import hashlib
import os
import pickle
from itertools import groupby
from os import path
from typing import Dict, IO, ByteString, List, Tuple, Union, Generator, NamedTuple, Type
from struct import Struct, calcsize, unpack
from glob import glob
from glob import iglob
from collections import Counter
from xxhash import xxh64_intdigest
from pathlib import Path

s_UInt16 = Struct('<H').unpack
s_Int32 = Struct('<l').unpack
s_UInt64 = Struct('<Q').unpack
s_WadHeader = Struct('<2sBB256sQL')
s_WadEntry = Struct('<QlllB?xxQ')
s_LinkHeader = Struct('<20xL52x').unpack
s_LinkInfo = Struct('<4xi8xi4xi').unpack

modtime = lambda p: int(path.getmtime(p) * 1000)

def s_ZString(f):
    data = (c for c in iter(lambda: bytes.replace(f.read(1), b'\x00', b''), b''))
    return b''.join(data).decode('ascii')

def s_ZWString(f):
    data = (c for c in iter(lambda: bytes.replace(f.read(2), b'\x00\x00', b''), b''))
    return b''.join(data).decode('utf-16-le')

def Link(fname: str) -> str:
    with open(fname, 'rb') as f:
        link_flags, = s_LinkHeader(f.read(76))
        if not (link_flags & 0x02) or link_flags & 0x100:
            return ""
        if link_flags & 0x01:
            size, = s_UInt16(f.read(2))
            f.seek(size, os.SEEK_CUR)
        
        offset = f.tell()
        hsize, o_local_path, o_common_path = s_LinkInfo(f.read(28))
        o_unicode_local_path = s_Int32(f.read(4))[0] if hsize > 28 else 0
        o_unicode_common_path = s_Int32(f.read(4))[0] if hsize > 32 else 0

        local_path = ""
        common_path = ""
        if o_unicode_local_path:
            f.seek(offset + o_unicode_local_path)
            local_path = s_ZWString(f)
        elif o_local_path:
            f.seek(offset + o_local_path)
            local_path = s_ZString(f)
        if o_unicode_common_path:
            f.seek(offset + o_unicode_common_path)
            common_path = s_ZWString(f)
        elif common_path:
            f.seek(offset + o_common_path)
            common_path = s_ZString(f)
        return common_path + local_path

class WadEntry(NamedTuple):
    key: int
    offset: int
    compressed_size: int
    uncompressed_size: int
    kind: int
    is_duplicate: bool
    sha256: int
    
    @staticmethod
    def create(data: bytes):
        return WadEntry(*s_WadEntry.unpack(data))

    def write_toc(self, outf: IO, diff: int, data_offset: int):
        outf.write(s_WadEntry.pack(\
            self.key, self.offset + diff, self.compressed_size, \
            self.uncompressed_size, self.kind, self.is_duplicate, self.sha256 \
        ))
        return data_offset
    
    def write_data(self, outf):
        pass

class ModEntry(NamedTuple):
    filepath: str
    key: int
    size: int
    sha256: int
    
    @staticmethod
    def create(filepath: str, key: int):
        #print(filepath, '->', key)
        with open(filepath, 'rb') as f:
            h  = hashlib.sha256()
            b  = bytearray(64*1024)
            mv = memoryview(b)
            for n in iter(lambda : f.readinto(mv), 0):
                h.update(mv[:n])
            sha256, = s_UInt64(h.digest()[:8])
            size = f.tell()
            return ModEntry(filepath, key, size, sha256)

    @staticmethod
    def create_list(modpath: str):
        modpath = path.normpath(modpath)
        entries = {}
        for filepath in iglob(f"{modpath}/*"):
            if path.isfile(filepath):
                try:
                    name = path.splitext(path.basename(filepath))[0]
                    key = int(name, 16)
                    entries[key] = ModEntry.create(filepath, key)
                except ValueError:
                    pass
        for filepath in iglob(f"{modpath}/*/**/*", recursive=True):
            if path.isfile(filepath):
                relpath = path.relpath(filepath, modpath).lower().replace('\\', '/')
                key = xxh64_intdigest(relpath)
                entries[key] = ModEntry.create(filepath, key)
            
        return entries

    def write_toc(self, outf: IO, diff: int, data_offset: int):
        outf.write(s_WadEntry.pack(\
            self.key, data_offset, self.size, self.size, 0, False, self.sha256\
        ))
        return data_offset + self.size
    
    def write_data(self, outf: IO):
        with open(self.filepath, 'rb') as inf:
            shutil.copyfileobj(inf, outf)

class Wad(NamedTuple):
    wadpath: str
    signature: bytes
    checksum: int
    entries: Dict[int, WadEntry]
    offset: int
    data_size: int

    @staticmethod
    def create(wadpath: str):
        with open(wadpath, 'rb') as f:
            header = s_WadHeader.unpack(f.read(s_WadHeader.size))
            magic, major, minor, signature, checksum, count = header
            assert magic == b'RW' and major == 3 and minor == 0
            size = s_WadEntry.size
            total = size * count
            data = f.read(total)
            offset = f.tell()
            f.seek(0, os.SEEK_END)
            data_size = f.tell() - offset
            entries_raw = (WadEntry.create(data[o:o+size]) for o in range(0, total, size))
            entries = { e.key: e for e in entries_raw }
            return Wad(wadpath, signature, checksum, entries, offset, data_size)            

    def write(self, outpath: str, modified: Dict[int, ModEntry]):
        os.makedirs(path.dirname(outpath), exist_ok=True)
        
        entries = {}
        entries.update(self.entries)
        oldcount = len(entries)
        entries.update(modified)
        newcount = len(entries)
        
        entries = sorted(entries.values(), key=lambda entry: entry.key)
        old = entries[0].key
        for x in range(1, len(entries)):
            assert old < entries[x].key
            old = entries[x].key
        
        diff = s_WadEntry.size * (newcount - oldcount)
        data_offset = self.offset + self.data_size + diff
        with open(outpath, 'wb') as outf:
            outf.write(s_WadHeader.pack(b'RW', 3, 0, self.signature, self.checksum, newcount))
            for entry in entries:
                data_offset = entry.write_toc(outf, diff, data_offset)
            with open(self.wadpath, 'rb') as inf:
                inf.seek(self.offset)
                shutil.copyfileobj(inf, outf)
            for entry in entries:
                entry.write_data(outf)

class ModOverlay:    
    def __init__(self, gamedir: str, modsdir: str, overlaydir: str):
        self.gamedir = gamedir
        self.modsdir = modsdir
        self.overlaydir = overlaydir
        self.gamedir_timestamp = 0
        self.modsdir_timestamp = 0
        self.modified_dirty = False
        self.overlaydir_timestamp = 0
        self.wads = {}
        self.key_lookup = {}
        self.mods = {}
        self.modified = {}

    @staticmethod
    def load(fpath: str):
        with open(fpath, 'rb') as f:
            return pickle.load(f, fix_imports=False)
    
    def save(self, fpath: str):
        with open(fpath, 'wb') as f:
            pickle.dump(self, f, protocol=4, fix_imports=False)
        
    def need_rebuild_game_index(self):
        return self.gamedir_timestamp != modtime(f'{self.gamedir}/DATA/FINAL')

    def rebuild_game_index(self):
        self.wads.clear()
        self.key_lookup.clear()
        for wadpath in iglob(f"{self.gamedir}/DATA/FINAL/**/*.wad.client", recursive=True):
            wad = Wad.create(wadpath)
            relpath = path.relpath(wadpath, self.gamedir).replace('\\', '/')
            self.wads[relpath] = wad
            for key in wad.entries.keys():
                self.key_lookup.setdefault(key, []).append(relpath)

        self.gamedir_timestamp = modtime(f'{self.gamedir}/DATA/FINAL')
        self.modified_dirty = True
        self.overlaydir_timestamp = 0
    
    def need_rebuild_mod_index(self):
        return self.modsdir_timestamp != modtime(self.modsdir)
    
    def rebuild_mod_index(self):
        self.mods.clear()
        for modpath in glob(f"{self.modsdir}/*"):
            if path.isdir(modpath):
                self.mods[modpath] = ModEntry.create_list(modpath)
        self.modsdir_timestamp = modtime(self.modsdir)
        self.modified_dirty = True
        self.overlaydir_timestamp = 0
    
    def need_rebuild_modified_index(self):
        return self.modified_dirty
    
    def rebuild_modified_index(self):
        self.modified.clear()
        processed = set()
        for mod in self.mods.values():
            found = {}
            missing = True
            for key, mod_entry in mod.items():
                if key in processed:
                    continue
                if key in self.key_lookup:
                    for wadpath in self.key_lookup[key]:
                        found[wadpath] = found.get(wadpath, 0) + 1
                        processed.add(key)
                        self.modified.setdefault(wadpath, {})[key] = mod_entry
                else:
                    missing = True
            if missing and found:
                wadpath, _ = max(found.items(), key=lambda kvp: kvp[1])
                for key, mod_entry in mod.items():
                    if key in processed:
                        continue
                    if not key in self.key_lookup:
                        self.modified[wadpath][key] = mod_entry
                        processed.add(key)
        self.modified_dirty = False
        self.overlaydir_timestamp = 0
    
    def need_rewrite(self):
        return self.overlaydir_timestamp != modtime(self.overlaydir)
    
    def write(self):
        written = set()
        for wadpath, mods in self.modified.items():
            p = f'{self.overlaydir}/{wadpath}'
            self.wads[wadpath].write(p, mods)
            written.add(Path(p))

        for filepath in iglob(f"{self.overlaydir}/**/*", recursive=True):
            if os.path.isfile(filepath) and not Path(filepath) in written:
                os.remove(filepath)

        self.overlaydir_timestamp = modtime(self.overlaydir)
    
    # Rebuilds caches as needed and writes as needed
    def auto_write(self):
        if self.need_rebuild_game_index():
            self.rebuild_game_index()
        if self.need_rebuild_mod_index():
            self.rebuild_mod_index()
        if self.need_rebuild_modified_index():
            self.rebuild_modified_index()
        if self.need_rewrite():
            self.write()
    
    # Performs full rebuild of cache and writes
    def force_write(self):
        self.rebuild_game_index()
        self.rebuild_mod_index()
        self.rebuild_modified_index()
        self.write()

def VerifyGameDir(gamedir):
    if gamedir.endswith('.lnk'):
        gamedir = Link(gamedir)
        
    if gamedir.endswith('.exe'):
        gamedir = path.dirname(gamedir)

    if path.exists(gamedir + '/Game/League of Legends.exe'):
        gamedir = gamedir + '/Game'
    
    if path.exists(gamedir + '/League of Legends.exe'):
        return path.normpath(gamedir).replace('\\', '/')
    
    return ""