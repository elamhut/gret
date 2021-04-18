from collections import namedtuple
from functools import wraps, lru_cache
from mathutils import Vector, Quaternion, Euler
import bpy
import io
import os
import re

from gret import prefs

def select_only(context, objs):
    """Ensures only the given object or objects are selected."""

    if not hasattr(objs, '__iter__'):
        objs = [objs]
    for obj in context.selected_objects:
        obj.select_set(False)
    for obj in objs:
        obj.hide_viewport = False
        obj.hide_select = False
        obj.select_set(True)
    context.view_layer.objects.active = next(iter(objs), None)

def show_only(context, objs):
    """Ensures only the given object or objects are visible in viewport or render."""

    if not hasattr(objs, '__iter__'):
        objs = [objs]
    for obj in context.scene.objects:
        obj.hide_viewport = True
        obj.hide_render = True
        obj.hide_select = True
    for obj in objs:
        obj.hide_viewport = False
        obj.hide_render = False
        obj.hide_select = False

def is_valid(data):
    """Returns whether a reference to a data-block is valid."""

    if not data:
        return False
    try:
        data.id_data
    except (ReferenceError, KeyError):
        return False
    return True

def get_context(active_obj=None, selected_objs=None):
    """Returns context for single object operators."""

    ctx = {}
    if active_obj and selected_objs:
        # Operate on all the objects, active object is specified
        ctx['object'] = ctx['active_object'] = active_obj
        ctx['selected_objects'] = ctx['selected_editable_objects'] = selected_objs
    elif not active_obj and selected_objs:
        # Operate on all the objects, it isn't important which one is active
        ctx['object'] = ctx['active_object'] = next(iter(selected_objs))
        ctx['selected_objects'] = ctx['selected_editable_objects'] = [active_obj]
    elif active_obj and not selected_objs:
        # Operate on a single object
        ctx['object'] = ctx['active_object'] = active_obj
        ctx['selected_objects'] = ctx['selected_editable_objects'] = [active_obj]
    return ctx

SelectionState = namedtuple('SelectionState', [
    'selected',
    'active',
    'layers',
    'objects',
])

def save_selection(all_objects=False):
    """Returns a SelectionState storing the current selection state."""

    return SelectionState(
        selected=bpy.context.selected_objects[:],
        active=bpy.context.scene.objects.active if not _280() else
            bpy.context.view_layer.objects.active,
        layers=bpy.context.scene.layers[:] if not _280() else
            [(c, c.hide_select, c.hide_viewport, c.hide_render) for c in bpy.data.collections],
        objects=[(o, o.hide_select, o.hide_viewport, o.hide_render) for o in bpy.data.objects],
    )

def load_selection(state):
    """Restores selection state from a SelectionState returned by save_selection()"""

    if not _280():
        bpy.context.scene.layers[:] = state.layers
    else:
        for collection, hide_select, hide_viewport, hide_render in state.layers:
            if is_valid(collection):
                collection.hide_select = hide_select
                collection.hide_viewport = hide_viewport
                collection.hide_render = hide_render
    for obj, hide_select, hide_viewport, hide_render in state.objects:
        if is_valid(obj):
            obj.hide_select = hide_select
            obj.hide_viewport = hide_viewport
            obj.hide_render = hide_render

    select_only(bpy.context, (obj for obj in state.selected if is_valid(obj)))

    if is_valid(state.active):
        bpy.context.view_layer.objects.active = state.active

def save_property(data, prop_path):
    if isinstance(prop_path, bpy.types.Property):
        prop = prop_path
        prop_path = prop.identifier
    else:
        dot_idx = prop_path.rindex('.')
        data = data.path_resolve(prop_path[:dot_idx], False)
        prop = data.bl_rna.properties[prop_path[dot_idx+1:]]

    # if not prop.is_runtime:
    if prop.is_readonly:
        return {}
    prop_id = prop.identifier
    try:
        if prop.type == 'COLLECTION':
            return prop_path, [save_property(subprop) for subprop in getattr(data, prop_id)]
        elif getattr(prop, 'is_array', False):
            return prop_path, getattr(data, prop_id)[:]
        else:
            print ("saving", prop_path, prop_id, getattr(data, prop_id))
            return prop_path, getattr(data, prop_id)
    except:
        raise
        # pass
    return None, None

def load_property(data, prop_path, value):
    if '.' in prop_path:
        dot_idx = prop_path.rindex('.')
        data = data.path_resolve(prop_path[:dot_idx], False)
        prop_id = prop_path[dot_idx+1:]
    else:
        prop_id = prop_path

    try:
        prop = data.bl_rna.properties[prop_id]
        if prop.type == 'COLLECTION':
            collection = getattr(data, prop_id)
            collection.clear()
            for saved_el in value:
                el = collection.add()
                load_properties(el, saved_el)
        elif not prop.is_readonly:
            print("setting", data, prop_id, prop.type, value, getattr(value, 'name', "noname"))
            setattr(data, prop_id, value)
            print("now=", getattr(data, prop_id))
    except:
        raise
        # pass

def save_object(data): #save_data
    """Returns a dictionary storing the properties of a Blender object."""

    saved = {}
    for prop in data.bl_rna.properties:
        prop_path, value = save_property(data, prop)
        if prop_id:
            saved[prop_id] = value
    return saved

def load_object(data, saved): #load_data
    """Restores properties from a dictionary returned by save_properties()"""

    for prop_path, value in saved.items():
        load_property(data, prop_path, value)

def is_defaulted(obj):
    """Returns whether the properties of an object are set to their default values."""
    # This is not extensively tested, it should work for most things

    for prop in obj.bl_rna.properties:
        if not prop.is_runtime:
            # Only consider user properties
            continue
        prop_id = prop.identifier
        try:
            if prop.type == 'COLLECTION':
                # Consider that if the collection has any elements, then it's not default
                current = len(getattr(obj, prop_id))
                default = 0
            elif prop.type == 'POINTER':
                current = getattr(obj, prop_id)
                default = None
            elif getattr(prop, 'is_array', False):
                current = getattr(obj, prop_id)[:]
                default = prop.default_array[:]
            else:
                current = getattr(obj, prop_id)
                default = getattr(prop, 'default', type(current)())

            if current != default:
                return False
        except TypeError:
            # The value type is not trivially initializable, omit it
            continue

    return True

def get_children_recursive(obj):
    for child in obj.children:
        yield child
        yield from get_children_recursive(child)

def get_flipped_name(name):
    """Returns the given name with flipped L/R affixes, or None if not applicable."""

    def flip_LR(s):
        if "L" in s.upper():
            return s.replace("l", "r").replace("L", "R")
        else:
            return s.replace("r", "l").replace("R", "L")

    match = re.match(r'(.+)([_\.][LlRr])$', name)  # Suffix
    if match:
        return match[1] + flip_LR(match[2])

    match = re.match(r'^([LlRr][_\.])(.+)', name)  # Prefix
    if match:
        return flip_LR(match[1]) + match[2]

    return None

def swap_object_names(obj1, obj2):
    name1, name2 = obj1.name, obj2.name
    obj1.name = name2
    obj2.name = name1
    obj1.name = name2

def beep(pitch=0, num=2):
    try:
        import winsound
        freq = 800 + 100 * pitch
        for _ in range(num):
            winsound.Beep(freq, 50)
    except:
        pass

def intercept(_func=None, error_result=None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not prefs.debug:
                # Redirect output
                stdout = io.StringIO()
                try:
                    from contextlib import redirect_stdout
                    with redirect_stdout(stdout):
                        result = func(*args, **kwargs)
                except Exception as e:
                    # import traceback
                    # traceback.print_exc()
                    result = error_result
            else:
                result = func(*args, **kwargs)
            return result
        return wrapper

    if _func is None:
        return decorator
    else:
        return decorator(_func)

def set_collection_viewport_visibility(context, collection_name, visibility=True):
    # Based on https://blenderartists.org/t/1141768
    # This is dumb as hell and hopefully it'll change in the future

    def get_viewport_ordered_collections(context):
        def add_child_collections(collection, out_list, add_self=True):
            if add_self:
                out_list.append(collection)
            for child in collection.children:
                out_list.append(child)
            for child in collection.children:
                add_child_collections(child, out_list, False)
        result = []
        add_child_collections(context.scene.collection, result)
        return result

    def get_area_from_context(context, area_type):
        for area in context.screen.areas:
            if area.type == area_type:
                return area
        return None

    # Find outliner index for the given collection name
    try:
        collections = get_viewport_ordered_collections(context)
        index, collection = next(((n, coll) for n, coll in enumerate(collections)
            if coll.name == collection_name))
    except StopIteration:
        return

    first_object = None
    if len(collection.objects) > 0:
        first_object = collection.objects[0]

    try:
        bpy.ops.object.hide_collection(context, collection_index=index, toggle=True)

        if first_object.visible_get() != visibility:
            bpy.ops.object.hide_collection(context, collection_index=index, toggle=True)
    except:
        context_override = context.copy()
        context_override['area'] = get_area_from_context(context, 'VIEW_3D')

        bpy.ops.object.hide_collection(context_override, collection_index=index, toggle=True)

        if first_object.visible_get() != visibility:
            bpy.ops.object.hide_collection(context_override, collection_index=index, toggle=True)

    return collection

def get_export_path(path, fields):
    """Returns an absolute path from an export path."""

    fields.update({
        'file': os.path.splitext(bpy.path.basename(bpy.data.filepath))[0],
    })
    path = path.format(**fields)

    if 'suffix' in fields:
        path, ext = os.path.splitext(path)
        path = path + fields['suffix'] + ext

    return bpy.path.abspath(path)

def fail_if_invalid_export_path(path, field_names):
    """Validates an export path and returns the reason it isn't valid."""

    if not path:
        raise Exception("Invalid export path.")

    if path.startswith("//") and not bpy.data.filepath:
        # While not technically wrong the file will likely end up at blender working directory
        raise Exception("Can't use a relative export path before the file is saved.")
    if os.path.isdir(path):
        raise Exception("Export path must be a file path.")

    # Check that the export path is valid
    try:
        fields = {s: "" for s in field_names}
        dirpath = os.path.dirname(get_export_path(path, fields))
    except Exception as e:
        raise Exception(f"Invalid export path: {e}")

    try:
        os.makedirs(dirpath)
    except PermissionError:
        raise Exception("Invalid export path.")
    except OSError:
        pass  # Directory already exists

def fail_if_no_operator(bl_idname, submodule=bpy.ops.object):
    """Checks an operator is available and returns the reason if it isn't."""

    try:
        # Use getattr, hasattr seems to always return True
        getattr(submodule, bl_idname)
    except AttributeError:
        raise Exception(f"Operator {bl_idname} is required and couldn't be found.")

def get_nice_export_report(filepaths, elapsed):
    """Returns text informing the user of the files that were exported."""

    if len(filepaths) > 5:
        return f"{len(filepaths)} files exported in {elapsed:.2f}s."
    if filepaths:
        filenames = [bpy.path.basename(filepath) for filepath in filepaths]
        return f"Exported {', '.join(filenames)} in {elapsed:.2f}s."
    return "Nothing exported."

def path_split_all(path):
    """Returns a path split into a list of its parts."""

    all_parts = []
    while True:
        parts = os.path.split(path)
        if parts[0] == path:  # Sentinel for absolute paths
            all_parts.insert(0, parts[0])
            break
        elif parts[1] == path:  # Sentinel for relative paths
            all_parts.insert(0, parts[1])
            break
        else:
            path = parts[0]
            all_parts.insert(0, parts[1])
    return all_parts

@lru_cache(maxsize=4095)
def levenshtein_distance(string1, string2):
    """Returns the minimum number of operations required to transform one string into the other."""

    if not string1:
        return len(string2)
    if not string2:
        return len(string1)
    if string1[0] == string2[0]:
        return levenshtein_distance(string1[1:], string2[1:])
    l1 = levenshtein_distance(string1, string2[1:])
    l2 = levenshtein_distance(string1[1:], string2)
    l3 = levenshtein_distance(string1[1:], string2[1:])
    return 1 + min(l1, l2, l3)

def remove_extra_data(obj):
    """Removes all data from a mesh object, except for the mesh itself."""

    obj.vertex_groups.clear()
    obj.shape_key_clear()
    if obj.type == 'MESH':
        mesh = obj.data
        mesh.use_customdata_vertex_bevel = False
        mesh.use_customdata_edge_bevel = False
        mesh.use_customdata_edge_crease = False
        # mesh.materials.clear() seems to crash
        while mesh.materials:
            mesh.materials.pop()
        while mesh.vertex_colors.active:
            mesh.vertex_colors.remove(mesh.vertex_colors.active)
        while mesh.uv_layers.active:
            mesh.uv_layers.remove(mesh.uv_layers.active)

def link_properties(from_obj, from_data_path, to_obj, to_data_path, invert=False):
    """Creates a simple driver linking properties between two objects."""

    if not to_obj.animation_data:
        to_obj.animation_data_create()
    fc = to_obj.driver_add(to_data_path)
    fc.driver.expression = '1 - var' if invert else 'var'
    fc.driver.type = 'SCRIPTED'
    fc.driver.use_self = True
    var = fc.driver.variables.new()
    var.name = 'var'
    var.type = 'SINGLE_PROP'
    tgt = var.targets[0]
    tgt.data_path = from_data_path
    tgt.id = from_obj

def make_annotations(cls):
    """Converts class fields to annotations if running Blender 2.8."""

    if bpy.app.version < (2, 80):
        return

    def is_property(o):
        try:
            return o[0].__module__ == 'bpy.props'
        except:
            return False
    bl_props = {k: v for k, v in cls.__dict__.items() if is_property(v)}
    if bl_props:
        if '__annotations__' not in cls.__dict__:
            setattr(cls, '__annotations__', {})
        annotations = cls.__dict__['__annotations__']
        for k, v in bl_props.items():
            annotations[k] = v
            delattr(cls, k)

def _280(true=True, false=False):
    return true if bpy.app.version >= (2, 80) else false
