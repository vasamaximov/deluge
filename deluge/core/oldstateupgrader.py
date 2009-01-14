#
# oldstateupgrader.py
#
# Copyright (C) 2008 Andrew Resch <andrewresch@gmail.com>
#
# Deluge is free software.
#
# You may redistribute it and/or modify it under the terms of the
# GNU General Public License, as published by the Free Software
# Foundation; either version 3 of the License, or (at your option)
# any later version.
#
# deluge is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with deluge.    If not, write to:
# 	The Free Software Foundation, Inc.,
# 	51 Franklin Street, Fifth Floor
# 	Boston, MA    02110-1301, USA.
#


import os
import os.path
import pickle
import cPickle
import shutil

try:
    import deluge.libtorrent as lt
except ImportError:
    import libtorrent as lt
    if not (lt.version_major == 0 and lt.version_minor == 14):
        raise ImportError("This version of Deluge requires libtorrent 0.14!")

from deluge.configmanager import ConfigManager
import deluge.core.torrentmanager
from deluge.log import LOG as log

#start : http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/286203
def makeFakeClass(module, name):
    class FakeThing(object):
        pass
    FakeThing.__name__ = name
    FakeThing.__module__ = '(fake)' + module
    return FakeThing

class PickleUpgrader(pickle.Unpickler):
    def find_class(self, module, cname):
        # Pickle tries to load a couple things like copy_reg and
        # __builtin__.object even though a pickle file doesn't
        # explicitly reference them (afaict): allow them to be loaded
        # normally.
        if module in ('copy_reg', '__builtin__'):
            thing = pickle.Unpickler.find_class(self, module, cname)
            return thing
        return makeFakeClass(module, cname)
# end: http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/286203

class OldStateUpgrader:
    def __init__(self):
        self.config = ConfigManager("core.conf")
        self.state05_location = os.path.join(self.config["config_location"], "persistent.state")
        self.state10_location = os.path.join(self.config["state_location"], "torrents.state")
        if os.path.exists(self.state05_location) and not os.path.exists(self.state10_location):
            # If the 0.5 state file exists and the 1.0 doesn't, then let's upgrade it
            self.upgrade05()

    def upgrade05(self):
        try:
            state = PickleUpgrader(open(self.state05_location, "rb")).load()
        except Exception, e:
            log.debug("Unable to open 0.5 state file: %s", e)
            return

        # Check to see if we can upgrade this file
        if type(state).__name__ == 'list':
            log.warning("0.5 state file is too old to upgrade")
            return

        new_state = deluge.core.torrentmanager.TorrentManagerState()
        for ti, uid in state.torrents.items():
            torrent_path = os.path.join(self.config["config_location"], "torrentfiles", ti.filename)
            try:
                torrent_info = None
                log.debug("Attempting to create torrent_info from %s", torrent_path)
                _file = open(torrent_path, "rb")
                torrent_info = lt.torrent_info(lt.bdecode(_file.read()))
                _file.close()
            except (IOError, RuntimeError), e:
                log.warning("Unable to open %s: %s", filepath, e)

            # Copy the torrent file to the new location
            import shutil
            shutil.copyfile(torrent_path, os.path.join(self.config["state_location"], str(torrent_info.info_hash()) + ".torrent"))

            # Set the file prioritiy property if not already there
            if not hasattr(ti, "priorities"):
                ti.priorities = [1] * torrent_info.num_files()

            # Create the new TorrentState object
            new_torrent = deluge.core.torrentmanager.TorrentState(
                torrent_id=str(torrent_info.info_hash()),
                filename=ti.filename,
                save_path=ti.save_dir,
                compact=ti.compact,
                paused=ti.user_paused,
                total_uploaded=ti.uploaded_memory,
                max_upload_speed=ti.upload_rate_limit,
                max_download_speed=ti.download_rate_limit,
                file_priorities=ti.priorities,
                queue=state.queue.index(ti)
            )
            # Append the object to the state list
            new_state.torrents.append(new_torrent)

        # Now we need to write out the new state file
        try:
            log.debug("Saving torrent state file.")
            state_file = open(
                os.path.join(self.config["state_location"], "torrents.state"), "wb")
            cPickle.dump(new_state, state_file)
            state_file.close()
        except IOError, e:
            log.warning("Unable to save state file: %s", e)
            return

        # Rename the persistent.state file
        try:
            os.rename(self.state05_location, self.state05_location + ".old")
        except Exception, e:
            log.debug("Unable to rename old persistent.state file! %s", e)
