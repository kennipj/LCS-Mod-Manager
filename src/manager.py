import atexit
import os
import zipfile
from shutil import rmtree, copy, copytree
import tkinter as tk
from tkinter import filedialog
from subprocess import Popen
from os import path
from wadmod import ModEntry, Wad, ModOverlay, VerifyGameDir


VERSION = 1.0

clean_string = lambda p: p.replace('\\', '/')

MSG_ERROR_DELETE = 0
MSG_ERROR_CONFLICT = 1
MSG_ERROR_OVERLAYDIR = 2
MSG_ERROR_GAMEDIR = 3
MSG_ERROR_MOD_NAME = 4
MSG_ERROR_STARTING_LCS = 5
MSG_ERROR_CLOSING_LCS = 6
MSG_DEFAULT_CUSTOM = 20
MSG_GOOD_CONFLICT = 39
MSG_GOOD_APPLY = 40
MSG_GOOD_STOPPED_LCS = 41
MSG_GOOD_STARTED_LCS = 42
MSG_GOOD_ADD = 43
MSG_GOOD_DELETE = 44
MSG_GOOD_DEFAULT = 99

class LabelEntry(tk.Frame):
    def __init__(self, master, text, arg):
        super().__init__(master)

        self.pack(fill=tk.X)
        self.master = master

        self.invalid = False
        self.label = tk.Label(self, text=text, width=9, anchor='e')
        self.label.pack(side=tk.LEFT, padx=5, pady=2)

        self.entry = tk.Entry(self, width=60)
        self.entry.bind('<FocusOut>', self.master.master.CheckDirs)
        self.entry.pack(side=tk.LEFT, fill=tk.X, padx=5)

        self.button = tk.Button(self, text='Browse', command= lambda: master.Browse(arg))
        self.button.pack(side=tk.LEFT, padx=5, pady=2)
    
    def __getitem__(self, key):
        if key == 'entry':
            return self.entry.get()
    
    def __setitem__(self, key, value):
        if key == 'entry':
            self.entry.delete(0, 'end')
            self.label.config()
            self.entry.insert(0, value)

class EntryPanel(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.gamedir_field = LabelEntry(self, 'Game dir:', 0)
        self.overlay_field = LabelEntry(self, 'Overlay dir:', 1)

    def Browse(self, id_: int):
        if id_:
            self.master.overlaydir = tk.filedialog.askdirectory(title='Select folder', initialdir=os.getcwd())
            self['overlaydir'] = self.master.overlaydir
        else:
            self.master.gamedir = VerifyGameDir(tk.filedialog.askopenfilename(title='Select League of Legends.exe'))
            self['gamedir'] = self.master.gamedir

        self.master.CheckDirs()
        with open('gamedir.txt', 'w') as f:
            f.write(self['gamedir'] + '\n' + self['overlaydir'])
    
    def __getitem__(self, key):
        if key == 'gamedir':
            return self.gamedir_field['entry']
        if key == 'overlaydir':
            return self.overlay_field['entry']
            
    def __setitem__(self, key, value):
        if key == 'gamedir':
            self.gamedir_field['entry'] = value
        if key == 'overlaydir':
            self.overlay_field['entry'] = value
        if key == 'game_label':
            self.gamedir_field.label.config(fg=value)
        if key == 'overlay_label':
            self.overlay_field.label.config(fg=value)

class MessagePanel(tk.Frame):
    #TODO: Maybe use bit fields instead?
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.label = tk.Label(self, text='')
        self.label.pack(pady=10)
        self.messages = {
            MSG_ERROR_DELETE: ['Unable to fully delete mod. Subdirectory open in another window.', 'red', True, False],
            MSG_ERROR_CONFLICT: ['You have asset conflicts, you must disable or remove conflicting mods.', 'red', False, False],
            MSG_ERROR_OVERLAYDIR: ['Invalid overlay directory, please browse to a valid directory', 'red', False, False],
            MSG_ERROR_GAMEDIR: ['Invalid game directory, please browse to target League of Legends.exe', 'red', False, False],
            MSG_ERROR_MOD_NAME: ['A mod with that name already exists, remove existing or rename', 'red', True, False],
            MSG_ERROR_STARTING_LCS: ['Failed to start lolcustomskin', 'red', True, False],
            MSG_ERROR_CLOSING_LCS: ['Failed to close lolcustomskin', 'red', True, False],
            MSG_DEFAULT_CUSTOM: ['', 'black', True, False],
            MSG_GOOD_CONFLICT: ['No mod conflicts detected.', 'green', True, False],
            MSG_GOOD_APPLY: ['Successfully applied mods.', 'green', True, False],
            MSG_GOOD_DELETE: ['Successfully deleted mod', 'green', True, False],
            MSG_GOOD_ADD: ['Successfully added mod.', 'green', True, False],
            MSG_GOOD_STOPPED_LCS: ['Successfully stopped lolcustomskin', 'green', True, False],
            MSG_GOOD_STARTED_LCS: ['Successfully launched lolcustomskin', 'green', True, False],
            MSG_GOOD_DEFAULT: ['Everything OK!', 'green', True, True],
        }
        self.errors = set([MSG_ERROR_DELETE, MSG_ERROR_CONFLICT,
                          MSG_ERROR_OVERLAYDIR, MSG_ERROR_GAMEDIR,
                          MSG_ERROR_MOD_NAME, MSG_ERROR_STARTING_LCS,
                          MSG_ERROR_CLOSING_LCS])

    def FlushGoodMsg(self):
        for prio, msg in self.messages.items():
            if msg[2] and prio != MSG_GOOD_DEFAULT and prio not in self.errors:
                msg[3] = False

    def UpdateMsg(self, custom=False):
        for prio, msg in self.messages.items():
            if msg[3]:
                if custom:
                    self.DisplayMsg(custom, msg[1], msg[2])
                else:
                    self.DisplayMsg(msg[0], msg[1], msg[2])
                break

    def DisplayMsg(self, text, color, allow_buttons):
        self.label.config(text=text, fg=color)
        if not allow_buttons:
            self.master.button_panel.apply_mods.config(state=tk.DISABLED)
            self.master.button_panel.start_lolcustomskin.config(state=tk.DISABLED)
        else:
            self.master.button_panel.apply_mods.config(state=tk.NORMAL)
            self.master.button_panel.start_lolcustomskin.config(state=tk.NORMAL)

    def AddMsg(self, id_, custom=False):
        self.FlushGoodMsg()
        self.messages[id_][3] = True
        self.UpdateMsg(custom)

    def RemoveMsg(self, id_):
        self.messages[id_][3] = False
        self.UpdateMsg()

class ModListbox(tk.Frame):
    def __init__(self, master, mods, text):
        super().__init__(master)

        self.label = tk.Label(self, text=text, anchor=tk.CENTER)
        self.label.pack()

        self.scrollbar = tk.Scrollbar(self, orient=tk.VERTICAL)

        self.list_box = tk.Listbox(self, selectmode = 'extended', yscrollcommand=self.scrollbar.set, width=30, height=13)
        self.scrollbar.config(command=self.list_box.yview)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 3))
        self.list_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=1)

        self.UpdateMods(mods)

    def UpdateMods(self, mods):
        self.list_box.delete(0, 'end')
        for name in mods.keys():
            self.list_box.insert(0, name)

    def GetIndex(self, val):
        return self.list_box.get(0, 'end').index(val)

    def SetColor(self, name, color):
        idx = self.list_box.get(0, 'end').index(name)
        self.list_box.itemconfig(idx, {'bg': color})

class ModButtons(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.remove_mods = tk.Button(self, text='->', command=lambda: self.MoveMods(1), width=4)
        self.remove_mods.pack(padx=(0, 3))
        self.add_mods = tk.Button(self, text='<-', command=lambda: self.MoveMods(-1), width=4)
        self.add_mods.pack(padx=(0, 3))

    def MoveMods(self, order: int):
        boxes = [self.master.enabled_box, self.master.disabled_box][::order]
        mods = [self.master.enabled_mods, self.master.disabled_mods][::order]
        selected = boxes[0].list_box.curselection()
        for idx in selected[::-1]:
            name = boxes[0].list_box.get(idx)
            boxes[1].list_box.insert(0, name)
            boxes[0].list_box.delete(idx)
            mods[1][name] = mods[0][name]
            del mods[0][name]
        self.master.master.CheckMods()
        

class ModFrame(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        try:
            with open('disabled.txt', 'r') as f:
                self.disabled_mods = {k.strip():None for k in f.readlines()}
        except IOError:
            open('disabled.txt', 'w').close()
            self.disabled_mods = {}

        self.enabled_mods = {k: v for k, v in master.mods.items() if k not in self.disabled_mods}
        self.disabled_mods = {k: v for k, v in master.mods.items() if k in self.disabled_mods}

        self.enabled_box = ModListbox(self, self.enabled_mods, 'Enabled mods')
        self.enabled_box.pack(side=tk.LEFT)

        self.buttons = ModButtons(self)
        self.buttons.pack(side=tk.LEFT)

        self.disabled_box = ModListbox(self, self.disabled_mods, 'Disabled mods')
        self.disabled_box.pack(side=tk.LEFT)

    def RefreshMods(self):
        #TODO: Restructure disabled mod storing
        #disabled_keys = set([val[0] for val in self.disabled_mods.values()])
        self.enabled_mods = {k: v for k, v in self.master.mods.items() if k not in self.disabled_mods}
        self.disabled_mods = {k: v for k, v in self.master.mods.items() if k in self.disabled_mods}
        self.enabled_box.UpdateMods(self.enabled_mods)
        self.disabled_box.UpdateMods(self.disabled_mods)

class ButtonPanel(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.apply_mods = tk.Button(self, text='Apply Mods', command= self.ApplyMods, width=15)
        self.apply_mods.pack(pady=1)
        self.refresh_mods = tk.Button(self, text='Refresh mods', command=self.RecheckMods, width=15)
        self.refresh_mods.pack(pady=1)
        self.add_mod = tk.Button(self, text='Add Mod Folder', command=self.AskDir, width=15)
        self.add_mod.pack(pady=1)
        self.extract_mods = tk.Button(self, text='Extract zip', command=self.AskZip, width=15)
        self.extract_mods.pack(pady=1)
        self.delete_mod = tk.Button(self, text='Delete Mod(s)', command=self.RemoveMods, width=15)
        self.delete_mod.pack(pady=1)
        self.start_lolcustomskin = tk.Button(self, text='Launch lolcustomskin', command=self.ToggleLCS,
                                             width=15, wraplength=80, height=3)
        self.start_lolcustomskin.pack(pady=10)

        #TODO: Support .WAD files, requires changes in wadmod.py
        #self.add_wad_mod = tk.Button(self, text='Add .WAD Mod', command=self.AskFile, width=15, state=tk.DISABLED)
        #self.add_wad_mod.pack(pady=1)



    def ToggleLCS(self):
        #TODO: Get messaging to work, requires reading from outside of main thread.
        if self.master.lcs_p_running:
            try:
                if self.master.lcs_p.poll is not None:
                    self.master.lcs_p.kill()
                    self.master.lcs_p.wait()
                self.master.msg_panel.RemoveMsg(MSG_ERROR_CLOSING_LCS)
                self.master.msg_panel.AddMsg(MSG_GOOD_STOPPED_LCS)
                self.master.lcs_p_running = False
                self.start_lolcustomskin.config(text='Launch lolcustomskin', state=tk.NORMAL)
            except:
                self.master.msg_panel.AddMsg(MSG_ERROR_CLOSING_LCS)
        else:
            try:
                self.master.lcs_p = Popen(['lolcustomskin.exe',  f'{self.master.overlaydir}/'])
                self.master.msg_panel.RemoveMsg(MSG_ERROR_STARTING_LCS)
                self.master.msg_panel.AddMsg(MSG_GOOD_STARTED_LCS)
                self.master.lcs_p_running = True
                self.start_lolcustomskin.config(text='Stop lolcustomskin', state=tk.NORMAL)
            except:
                self.master.msg_panel.AddMsg(MSG_ERROR_STARTING_LCS)
    
    def RecheckMods(self):
        self.master.GetMods()
        self.master.mod_panel.RefreshMods()
        self.master.CheckMods()

    def AskDir(self):
        dir_ = tk.filedialog.askdirectory(title='Select folder')
        try:
            copytree(dir_, 'mods/' + path.basename(dir_))
            self.RecheckMods()
        except FileExistsError:
            self.master.msg_panel.AddMsg(MSG_ERROR_MOD_NAME)
        except FileNotFoundError:
            pass

    def AskZip(self):
        zip_path = tk.filedialog.askopenfilename(title='Select zip file')
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(self.master.modsdir)
            self.RecheckMods()
        except FileExistsError:
            self.master.msg_panel.AddMsg(MSG_ERROR_MOD_NAME)
        except FileNotFoundError:
            pass

    def AskFile(self):
        file_ = tk.filedialog.askopenfilename(title='Select .wad file')
        try:
            copy(file_, 'mods/' + path.basename(file_))
            self.RecheckMods()
        except FileExistsError:
            self.master.msg_panel.AddMsg(MSG_ERROR_MOD_NAME)
        except FileNotFoundError:
            pass

    def ApplyMods(self):
        #TODO: Check if mod is valid
        gamedir = VerifyGameDir(self.master.gamedir)
        if gamedir and self.master.overlaydir:
            ModOverlay(self.master.gamedir, self.master.modsdir, self.master.overlaydir, self.master.mod_panel.disabled_mods).force_write()
        self.master.msg_panel.AddMsg(MSG_GOOD_APPLY)

    def RemoveMods(self):
        to_remove = []
        disabled_list = self.master.mod_panel.disabled_box.list_box
        enabled_list = self.master.mod_panel.enabled_box.list_box
        
        self.RemoveMod(disabled_list, self.master.mod_panel.disabled_mods)
        self.RemoveMod(enabled_list, self.master.mod_panel.enabled_mods)

    def RemoveMod(self, mod_list, mods):
        to_remove = []
        for idx in mod_list.curselection():
            name = mod_list.get(idx)
            if path.isdir('mods/' + name):
                try:
                    rmtree('mods/' + name)
                    #self.master.msg_panel.RemoveMsg(MSG_ERROR_DELETE)
                except OSError:
                    pass
                    #self.master.msg_panel.AddMsg(MSG_ERROR_DELETE, custom=f'Unable to fully delete {name}. Subdirectory open in another window.')
                    #continue
            else:
                os.remove('mods/' + name)
            to_remove.append((name, idx))
            del mods[name]
            self.master.msg_panel.AddMsg(MSG_GOOD_DELETE, custom=f'Successfully deleted {name}')

        if len(mod_list.curselection()) > 1:
            self.master.msg_panel.AddMsg(MSG_GOOD_DELETE, custom=f'Successfully deleted {len(mod_list.curselection())} mods')

        for key, idx in to_remove[::-1]:
            mod_list.delete(idx)
            del self.master.mods[key]
        self.master.CheckMods()

class ModManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'lolcustomskin - Mod Manager v{VERSION}')
        self.geometry('650x350+500+500')

        self.MakeDirs()

        self.entry_panel = EntryPanel(self)
        self.entry_panel.grid(row=0, column=0)

        self.msg_panel = MessagePanel(self)
        self.msg_panel.grid(row=1, column=0)

        self.button_panel = ButtonPanel(self)
        self.button_panel.grid(column=1)

        self.GetDirs()

        self.modsdir = 'mods/'
        self.gamedir = self.entry_panel['gamedir']
        self.overlaydir = self.entry_panel['overlaydir']
        self.GetMods()

        self.mod_panel = ModFrame(self)
        self.mod_panel.grid(row=2, column=0)

        self.lcs_p_running = False

        self.CheckMods()
        self.CheckDirs()
        self.QueryProcess()

    def GetMods(self):
        mods = [dir_ for dir_ in os.listdir(self.modsdir) if path.isdir(path.join(self.modsdir, dir_))]
        self.mods = {modpath:ModEntry.create_list(self.modsdir + modpath) for modpath in mods}

    def MakeDirs(self):
        os.makedirs('overlay/', exist_ok=True)
        os.makedirs('mods/', exist_ok=True)

    def QueryProcess(self):
        if self.lcs_p_running:
            if self.lcs_p.poll() is not None:
                self.msg_panel.AddMsg(MSG_DEFAULT_CUSTOM, 'lolcustomskin has terminated.')
                self.button_panel.start_lolcustomskin.config(text='Launch lolcustomskin', state=tk.NORMAL)
                self.lcs_p_running = False
            else:
                self.msg_panel.AddMsg(MSG_DEFAULT_CUSTOM, 'lolcustomskin is running...')
        self.after(100, self.QueryProcess)
        

    def CheckDirs(self, *args):
        valid_game_dir = bool(VerifyGameDir(self.entry_panel['gamedir']))
        valid_overlay_dir = os.path.exists(self.entry_panel['overlaydir']) and os.path.isdir(self.entry_panel['overlaydir'])
        self.msg_panel.RemoveMsg(MSG_ERROR_OVERLAYDIR)
        self.msg_panel.RemoveMsg(MSG_ERROR_GAMEDIR)
        self.entry_panel['game_label'] = 'black'
        self.entry_panel['overlay_label'] = 'black'

        if not valid_overlay_dir:
            self.button_panel
            self.msg_panel.AddMsg(MSG_ERROR_OVERLAYDIR)
            self.entry_panel['overlay_label'] = 'red'
        
        if not valid_game_dir:
            self.msg_panel.AddMsg(MSG_ERROR_GAMEDIR)
            self.entry_panel['game_label'] = 'red'

    def GetDirs(self):
        try:
            with open('gamedir.txt', 'r') as f:
                self.entry_panel['gamedir'] = f.readline().strip()
                self.entry_panel['overlaydir'] = f.readline().strip()
        except IOError:
            with open('gamedir.txt', 'w') as f:
                default_overlaydir = clean_string(os.getcwd()) + '/overlay'
                f.write('\n' + default_overlaydir)
                self.entry_panel['overlaydir'] = default_overlaydir

    def CheckMods(self):
        self.processed = {}
        for key, values in self.mod_panel.enabled_mods.items():
            for val in values.values():
                asset_path = '/'.join(clean_string(val[0]).split('/')[2:])
                self.CheckMod(asset_path, key)
        conflicted_mods = {}
        conflicts = False
        for key, val in self.processed.items():
            for name in val:
                if len(val) > 1:
                    conflicts = True
                    conflicted_mods[name] = True
                elif name not in conflicted_mods:
                    conflicted_mods[name] = False

        for name, conflict in conflicted_mods.items():
            if conflict:
                self.mod_panel.enabled_box.SetColor(name, 'red')
            else:
                self.mod_panel.enabled_box.SetColor(name, 'white')

        if conflicts:
            self.msg_panel.AddMsg(MSG_ERROR_CONFLICT)
        else:
            self.msg_panel.AddMsg(MSG_GOOD_DEFAULT)
            self.msg_panel.RemoveMsg(MSG_ERROR_CONFLICT)


    def CheckMod(self, asset_path, name):
        if asset_path in self.processed:
            self.processed[asset_path].append(name)
        else:
            self.processed[asset_path] = [name]

    def SaveDisabled(self):
        with open('disabled.txt', 'w') as f:
            f.writelines(k + '\n' for k in self.mod_panel.disabled_mods.keys())


if __name__ == '__main__':
    mod_manager = ModManager()
    atexit.register(mod_manager.SaveDisabled)
    mod_manager.mainloop()