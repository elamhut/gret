from collections import defaultdict
import bpy
import time

from gret.helpers import load_property, save_property
from gret.log import logger, log, logd

class Operator(bpy.types.Operator):
    save_context_props = []
    save_mesh_props = []
    save_selection = False
    push_undo = False

    # exported_files = []
    saved_props = None
    # save_mode = True

    def run(self, context):
        pass

    def get_saved_meshes():
        return bpy.data.meshes

    def execute(self, context):
        logger.start_logging()

        self.saved_props = defaultdict(list)
        self.exported_files = []

        for path in self.save_context_props:
            logd(f"Saving context property {path}")
            prop_id, value = save_property(context, path)
            if prop_id:
                self.saved_props[context].append((prop_id, value))

        for path in self.save_mesh_props:
            meshes = self.get_saved_meshes()
            logd(f"Saving property {path} for {len(meshes)} meshes")
            for mesh in meshes:
                prop_id, value = save_property(mesh, path)
                if prop_id:
                    self.saved_props[mesh].append((prop_id, value))

        try:
            start_time = time.time()
            result = self.run(context)
            elapsed = time.time() - start_time
            # self.report({'INFO'}, get_nice_export_report(self.exported_files, elapsed))
        except:
            result = {'CANCELLED'}
        finally:
            for data, saved in self.saved_props.items():
                # if not is_valid
                for prop_id, value in saved:
                    load_property(data, prop_id, value)
                    logd(f"Restoring setting {prop_id}")
            del self.saved_props
            logger.end_logging()

        if self.push_undo:
            bpy.ops.ed.undo_push()

        return result