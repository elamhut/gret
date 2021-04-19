from collections import defaultdict
import bpy
import time

from gret.helpers import (
    get_nice_export_report,
    is_valid,
    load_property,
    save_property,
    select_only,
)
from gret.log import logger, log, logd

class Operator(bpy.types.Operator):
    # save_mode = True
    save_selection = False
    save_context_props = []
    save_object_props = []
    save_mesh_props = []
    push_undo = False

    def run(self, context):
        pass

    def get_saved_objects(self, context):
        return context.scene.objects

    def get_saved_meshes(self, context):
        return bpy.data.meshes

    def execute(self, context):
        logger.start_logging()

        self.saved_props = defaultdict(list)
        self.exported_files = []

        if self.save_selection:
            self.saved_selection = context.selected_objects[:]
            self.saved_active = context.view_layer.objects.active

        for path in self.save_context_props:
            logd(f"Saving context property {path}")
            prop_id, value = save_property(context, path)
            if prop_id:
                self.saved_props[context].append((prop_id, value))

        for path in self.save_object_props:
            objects = self.get_saved_objects(context)
            logd(f"Saving property {path} for {len(objects)} objects")
            for obj in objects:
                prop_id, value = save_property(obj, path)
                if prop_id:
                    self.saved_props[obj].append((prop_id, value))

        for path in self.save_mesh_props:
            meshes = self.get_saved_meshes(context)
            logd(f"Saving property {path} for {len(meshes)} meshes")
            for mesh in meshes:
                prop_id, value = save_property(mesh, path)
                if prop_id:
                    self.saved_props[mesh].append((prop_id, value))

        try:
            start_time = time.time()
            result = self.run(context)
            elapsed = time.time() - start_time
            if self.exported_files:
                self.report({'INFO'}, get_nice_export_report(self.exported_files, elapsed))
        except:
            # result = {'CANCELLED'}
            raise
        finally:
            for data, saved in self.saved_props.items():
                if is_valid(data):
                    for prop_id, value in saved:
                        load_property(data, prop_id, value)
                        logd(f"Restoring setting {prop_id}")
            del self.saved_props

            if self.save_selection:
                select_only(bpy.context, (obj for obj in self.saved_selection if is_valid(obj)))
                if is_valid(self.saved_active):
                    context.view_layer.objects.active = self.saved_active
                del self.saved_selection
                del self.saved_active

            del self.exported_files

            logger.end_logging()

        if self.push_undo:
            bpy.ops.ed.undo_push()

        return result