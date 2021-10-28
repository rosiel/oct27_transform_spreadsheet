#!/usr/local/bin/python3
# vim: set expandtab:
# vim: tabstop=4:
# vim: ai:
# vim: shiftwidth=4:

import csv
import optparse
import os
import yaml
import sys
import edtf_validate.valid_edtf
import requests
import datetime
from requests.auth import HTTPBasicAuth


## Run this script with an input file.

## TODO: how to get photo credit in?
## TODO: Read directly from spreadsheet.
## TODO: what are we doing with files without extensions

def parse_cmd_line():
    parser = optparse.OptionParser(usage="%prog [options] INPUT_FILE")
    parser.add_option("--data-dir", dest="data_dir", default = "data", help="path to directory containing files (\"Views\").")
    parser.add_option("--skip-file-check", dest="skip_file_check", action="store_true", default = False, help="path to directory containing files (\"Views\").")
    opts, args = parser.parse_args()

    if len(args) < 1:
        parser.error("Need at least one input file on command line.")

    return opts.data_dir, opts.skip_file_check, args

def read_in_dict_file(filename, key_col, val_col, silent = False):
    """
    For csv file filename, create a dictionary where the
    values in key_col point to their corresponding values
    in val_col.

    Will bark if key_col is blank or duplicate.
    :param filename:
    :param key_col:
    :param val_col:
    :param silent:
    :return:
    """
    data_dict = {}
    key_errors = set()
    with open(filename, 'r') as f:
        reader = csv.DictReader(f, delimiter=',')
        row_count = 1
        for row in reader:
            row_count += 1
            if row[key_col] == '':
                if not silent:
                    print("NOTICE: Row [{}] in file [{}]: key column {} is blank. Skipping row.".format(row_count, filename, key_col))
                key_errors.add("blanks")
                continue
            if row[key_col] in data_dict.keys():
                if not silent:
                    print("NOTICE: Row [{}] in file [{}]: overwriting existing entry: [{}, {}]".format(row_count, filename, row[key_col], data_dict[row[key_col]]))
                key_errors.add("dupes")
            data_dict[row[key_col]] = row[val_col]
    return data_dict, key_errors

def get_draft_items(filename, key_col, val_col, blank_col):
    """
    like read_in_dict_file but only gets values where blank_col is blank.
    Useful after read_in_dict if there's a backup column when the original
    key_col was blank.
    :param filename:
    :param key_col:
    :param val_col:
    :param blank_col:
    :return:
    """
    data_dict = {}
    with open(filename, 'r') as f:
        reader = csv.DictReader(f, delimiter=',')
        for row in reader:
            if not row[blank_col]:
                data_dict[row[key_col]] = row[val_col]
    return data_dict

def get_drupal_lookups(objects_file, media_file, item_file, host = ''):
    if os.path.isfile(objects_file):
        objects, key_errors = read_in_dict_file(objects_file, "field_object_identifier", "node_id")
        if 'blanks' in key_errors:
            print("ERROR in existing data: some objects are missing identifiers. Go here to fix:\n   {}/object-index".format(host))
        if 'dupes' in key_errors:
            print("ERROR in existing data: some objects have duplicate identifiers. Go here to fix:\n    {}/object-index".format(host))
        else:
            print("OK: Found {} objects.".format(len(objects)))
    else:
        raise FileNotFoundError

    if os.path.isfile(media_file):
        media, media_key_errors = read_in_dict_file(media_file, "filename", "media_id")
        print("OK: found {} media.".format(len(media)))
    else:
        raise FileNotFoundError

    if os.path.isfile(item_file):
        items, item_key_errors = read_in_dict_file(item_file, "field_item_id", "term_id", silent=True)
        drafts = get_draft_items(item_file, "Name", "term_id", "field_item_id")
        dupes = set(items.keys()).intersection(set(drafts.keys()))
        if len(dupes) > 0:
            print("ERROR: Item 'drafts' duplicate existing Items that aren't drafts. [{}]".format(dupes))

        print("OK: Found existing completed items: {}".format(len(items)))
        print("OK: Found existing draft items: {}".format(len(drafts)))

    else:
        raise FileNotFoundError

    if len(key_errors) > 0 or len(media_key_errors) > 0 or ('dupes' in item_key_errors) or len(dupes) > 0:
        raise ValueError("Drupal data contains inconsistencies. Identifiers should be unique.")

    return objects, media, items, drafts


def read_in_yaml(filename):
    with open(filename, 'r') as stream:
        try:
            data = yaml.safe_load(stream)
            return data
        except yaml.YAMLError as exc:
            print(exc)
            raise

def get_workbench_creds():
    filename = 'conf' + os.sep + 'credentials.yml'
    if not os.path.isfile(filename):
        raise InputError("Config file not found at conf\credentials.yml.")
    creds = read_in_yaml(filename)
    if not (creds['host'] and creds['password'] and creds['username']):
        raise ConnectionError("Credentials must contain host, password, and username.")
    return creds

class InputError(Exception):
    def __init__(self, message):
        self.message = message

class ValueError(Exception):
    def __init__(self, message):
        self.message = message

def update_csv_indexes(creds):
    """

    :param creds: workbench credentials dictionary containing username, password, host
    :param path: path to a view that downloads csv
    :return:
    """
    types = ['item','object','media']
    for type in types:
        url = creds['host']  + '/' + type + '-index/download'
        response = requests.get(
            url,
            auth=(creds['username'], creds['password']),
            headers={"Content-Type": "text/csv", "User-Agent": 'Islandora Workbench'}
        )
        if response.status_code == 200:
            with open(type + '_index.csv', 'w') as f:
                f.write(response.text)
        else:
            raise ConnectionError("Failed to get {} index at {}.".format(type, url))
    return "object_index.csv", "media_index.csv", "item_index.csv"


def get_type_config(type):
    config_file = sys.path[0] + os.sep + 'conf' + os.sep + type + '.yml'
    return read_in_yaml(config_file)

def validate_edtf_date(date):
    valid = edtf_validate.valid_edtf.is_valid(date.strip())
    return valid


class Row(object):
    def __init__(self, row, row_id):
        self.id = False
        self.id_in_drupal = False
        self.structural_issues = False
        self.value_issues = False
        self.thumbnail_mid = False
        self.parent = False
        self.row = row
        self.row_number = row_id
        for key in self.row:
            self.row[key] = self.row[key].strip()
        self.blank = '' # Hack for workbench needing a 'file' column

    def __str__(self):
        string = ''
        for attr, value in self.__dict__.items():
            string += str(attr) +': '+ str(value) + ', '
        return string

    def values(self):
        values = {}
        for attr, value in self.__dict__.items():
            values[attr] = value
        del values["row"]
        values.update(self.row)
        return values



    def check_for_self_in_drupal(self, objects):
        if self.id in objects.keys():
            self.id_in_drupal = self.row["id_in_drupal"] = objects[self.id]
            return True
        else:
            return False

    def check_for_thumbnail(self, media):
        if self.row["FILENAME"] in media.keys():
            self.thumbnail_mid = media[self.row["FILENAME"]]
            return True
        else:
            return False

    def validate_fields(self):
        # HACK FOR FILES WITHOUT EXTENSIONS
        if len(self.row["FILENAME"]) > 4:
            if self.row["FILENAME"][-4] != '.':
                self.row["FILENAME"] = self.row["FILENAME"] + '.jpg'



class Object(Row):
    def __init__(self, row, row_id = None):
        super().__init__(row, row_id)
        self.id = self.row["OBJECT"]
        self.row['id'] = self.id

    def validate_structure(self, objects, items):
        # OBJECT ID exists
        if self.row["OBJECT"] == '':
            print("ERROR: Line {}. OBJECT ID is MANDATORY. ".format(self.row_number))
            self.structural_issues = True

        # OBJECT IDs UNIQUE
        if self.id in objects.keys():
            print("ERROR: Line {}. OBJECT IDs must be unique. [{}]".format(self.row_number, self.id))
            self.structural_issues = True

        # ITEM ID IS VALID
        if self.row["ITEM"] not in items.keys():
            print("ERROR: Line {}. Object {} names item id {}; item not found.".format(self.row_number, self.id, self.row["ITEM"]))
            self.structural_issues = True
        else:
            self.parent = self.row["ITEM"]

    def validate_fields(self):
        super().validate_fields()
        # TITLE IS MANDATORY
        if self.row["TITLE"] == '':
            print("ERROR: Line {}.  Object title is mandatory. No title found for [{}].".format(self.row_number, self.row["OBJECT"]))
            self.value_issues = True

        # CHECK DATES.
        date = self.row["DATE"]
        if "N/A" in date:
            print("WARNING: Line {}. 'N/A' is redundant as a date, removing.".format(self.row_number))
            date = self.row["DATE"] = ''
        if date != '':
            valid = validate_edtf_date(date)
            if not valid:
                print("ERROR: Line {}. BAD DATE. [{}] is not a valid EDTF date.".format(self.row_number, date))
                self.value_issues = True


class Item(Row):
    def __init__(self, row, row_id = None):
        super().__init__(row, row_id)
        self.is_draft = False
        self.id = self.row["ITEM"]
        self.row['id'] = self.id

    def check_for_self_in_drafts(self, drafts):
        if self.id in drafts:
            self.id_in_drupal = drafts[self.id]
            self.is_draft = True
            return True
        else:
            return False

    def validate_structure(self, objects, items):
        # ITEM ID exists
        if self.id == '':
            print("ERROR: Line {}. ITEM ID is MANDATORY. ".format(self.row_number))
            self.structural_issues = True

        # ITEM IDs UNIQUE
        if self.row["ITEM"] in items.keys():
            print("ERROR: Line {}. ITEM IDs must be unique. [{}].".format(self.row_number, self.row["ITEM"]))
            self.structural_issues = True

        return self.structural_issues

    def validate_fields(self):
        super().validate_fields()
        # TITLE IS MANDATORY
        if self.row["TITLE"] == '':
            print("ERROR: Line {}. Item title is mandatory. No title found for [{}].".format(self.row_number, self.id))
            self.value_issues = True

        # CHECK DATES.
        date = self.row["DATE"]
        if "N/A" in date:
            print("WARNING: Line {}. 'N/A' is redundant as a date, removing.".format(self.row_number, ))
            date = self.row["DATE"] = ''
        if date != '':
            valid = validate_edtf_date(date)
            if not valid:
                print("ERROR: Line {}. BAD DATE. [{}] is not a valid EDTF date.".format(self.row_number, date))
                self.value_issues = True


class View(Row):
    def __init__(self, row, row_id = None):
        super().__init__(row, row_id)
        self.id = self.row["FILENAME"]
        self.has_file = False
        if self.id == '':
            print("ERROR: Line {}. View requires a filename".format(self.row_number))
            self.structural_issues = True


    def validate_structure(self, objects, items):

        # OBJECT IS MANDATORY.
        if self.row["OBJECT"] == '':
            print("ERROR: Line {}. View {} requires an object.".format(self.row_number, self.id))
            self.structural_issues = True
            # FIXME allow updates?
        elif self.row["OBJECT"] not in objects.keys():
            print("ERROR: Line {}. View {} names object id {}; Object not found.".format(self.row_number, self.row["FILENAME"], self.row["OBJECT"]))
            self.structural_issues = True
        else:
            self.parent = self.row["OBJECT"]

    def validate_fields(self):
        super().validate_fields()
        self.id = self.row["FILENAME"]

    def check_for_file(self, files):
        if self.row['FILENAME'] in files:
            self.has_file = True
        else:
            # Remove extension
            root = os.path.splitext(self.row["FILENAME"])[0]
            matches = [ x for x in files if x.startswith(root) ]
            if len(matches) == 1:
                self.row["FILENAME"] = self.id = matches[0]
            elif len(matches) > 1:
                self.value_issues = True
                print("ERROR: Multiple matching files found in data dir: {} ".format(str(matches)))

class Analysis(object):
    def __init__(self, objects, items, views):
        self.object_count_total = len(objects.values())
        self.item_count_total = len(items.values())
        self.view_count_total = len(views.values())
        self.object_existing_total = len([ x for x in objects.values() if x.id_in_drupal ])
        self.item_existing_total = len([ x for x in items.values() if x.id_in_drupal ])
        self.view_existing_total = len([ x for x in views.values() if x.id_in_drupal ])
        self.item_existing_drafts = len([x for x in items.values() if x.is_draft])
        self.object_error_count = len([ x for x in objects.values() if (x.structural_issues or x.value_issues)])
        self.item_error_count = len([ x for x in items.values() if (x.structural_issues or x.value_issues)])
        self.view_error_count = len([ x for x in views.values() if (x.structural_issues or x.value_issues)])
        self.view_has_file = len([ x for x in views.values() if x.has_file])
        self.new_view_has_file = len([ x for x in views.values() if x.has_file and not x.id_in_drupal])
        self.items_for_thumbs = len([x for x in items.values() if (x.thumbnail_mid and x.id_in_drupal)])
        self.objects_for_thumbs = len([x for x in objects.values() if (x.thumbnail_mid and x.id_in_drupal)])
        new_objects = set([ x.id for x in objects.values() if not x.id_in_drupal ])
        self.new_objects_with_items = len(set([ x.parent for x in views.values() if x.has_file and x.parent in new_objects ]))




def print_report(stats):

    print("Total objects: {}".format(stats.object_count_total))
    if stats.object_error_count > 0:
        print("  Objects with ERRORS: {}".format(stats.object_error_count))
    print("  New objects: {}".format(stats.object_count_total - stats.object_existing_total))
    print("  Objects already in Drupal: {}".format(stats.object_existing_total))

    print("Total items: {}".format(stats.item_count_total))
    if stats.item_error_count > 0:
        print("  Items with ERRORS: {}".format(stats.item_error_count))
    print("  New items: {}".format(stats.item_count_total - stats.item_existing_total))
    print("  Items already in Drupal: {}".format(stats.item_existing_total))
    print("    Incomplete, needing updates: {}".format(stats.item_existing_drafts))

    print("Total views: {}".format(stats.view_count_total))
    if stats.view_error_count > 0:
        print("  Views with ERRORS: {}".format(stats.view_error_count))

    print("  Views already in Drupal: {}".format(stats.view_existing_total))
    print("  New view data: {}".format(stats.view_count_total - stats.view_existing_total))
    print("      With files to ingest: {}".format(stats.new_view_has_file))

    print("THUMBNAILS available for existing objects:")
    print("  items for thumbs: {}".format(stats.items_for_thumbs))
    print("  objects for thumbs: {}".format(stats.objects_for_thumbs))

def output_objects_as_csv(filename, object_list, field_config):
    # Write CSV
    with open(filename, 'w') as f:
        writer = csv.DictWriter(f, fieldnames = field_config, extrasaction='ignore')
        writer.writerow(field_config)
        for obj in object_list:
            writer.writerow(obj.values())

def prepare_objects_with_views(all_objects, views, new_objects = True, only_available_files = False):
    max_view_count = 0
    objects = []
    if new_objects:
        temp_object_list = [ obj for obj in all_objects.values() if obj.id_in_drupal == False ]
    else:
        temp_object_list = [ obj for obj in all_objects.values() if obj.id_in_drupal == False ]

    for obj in temp_object_list:
        if only_available_files:
            children = [ x for x in views.values() if x.parent == obj.id and x.has_file and not x.id_in_drupal ]
        else:
            children = [ x for x in views.values() if x.parent == obj.id and not x.id_in_drupal]
        max_view_count = max([len(children), max_view_count])
    print("max view count: {}".format(max_view_count))
    headers = ['file'] + [ "file_" + str(x) for x in range(max_view_count-1)]
    print(headers)

    for obj in temp_object_list:
        if only_available_files:
            children = [ x for x in views.values() if x.parent == obj.id and x.has_file and not x.id_in_drupal]
        else:
            children = [ x for x in views.values() if x.parent == obj.id and not x.id_in_drupal ]
        my_views = [ child.id for child in children ]
        if len(my_views) > 0:
            objects.append(obj)
        diff = max_view_count-len(my_views)
        if diff > 0:
            my_views = my_views + [''] * diff
        # save the views as columns in the row of the object.
        obj.row.update(dict(zip(headers,my_views)))
        # print(obj.row)
    return objects, headers

def output_workbench_config(filename, task, input_csv, input_dir, additional_files = None, **options):
    write_workbench_config(filename, task, input_csv, input_dir, additional_files, **options)
    print("Use the following argument for workbench:\n  --config {} --check\n".format( os.path.abspath(filename)))

def write_workbench_config(filename, task, input_csv, input_dir, additional_files = None, **options  ):
    data = {}
    data['task'] = task
    data.update(get_workbench_creds())
    data['content_type'] = 'archival_object'
    data['input_csv'] =  os.path.abspath(input_csv)
    data['input_dir'] =  os.path.abspath(input_dir)
    data['allow_adding_terms'] = True
    data.update(options)
    if additional_files:
        data['additional_files'] = [ {x: 5} for x in additional_files]
    with(open(filename, 'w')) as f:
        doc = yaml.dump(data,f, sort_keys = False, default_style = '"')

def main():
    data_dir, skip_file_check, input_filenames = parse_cmd_line()

    # TODO: make optional, to process structure of file alone.
    # Get data about existing objects, media, or files.
    try:
        creds = get_workbench_creds()
        object_index_filename, media_index_filename, item_index_filename = update_csv_indexes(creds)
        objects_in_drupal, media_in_drupal, items_in_drupal, drafts_in_drupal = get_drupal_lookups(object_index_filename, media_index_filename, item_index_filename)
    except yaml.YAMLError:
        print("ERROR: Credentials in conf/credentials.yml is not valid YAML.")
        exit(1)
    except InputError as err:
        print("ERROR: {}".format(err))
        print("Please ensure your drupal credentials are in conf/credentials.yml.")
        exit(1)
    except ConnectionError as err:
        print("ERROR: {}".format(err))
        exit(1)
    except ValueError as err:
        print("ERROR: {}".format(err))
        print("Fix inconsistencies in the Drupal data before continuing.")
        exit(1)


    # Check against file in data-dir

    objects = {}
    items = {}
    views = {}
    # names = {}

    if not skip_file_check:
        if not os.path.isdir(data_dir):
            print("WARNING: Data directory not available, so we're going to skip over the files this run. Provide the path to the files in the --data-dir parameter, or use the --skip-file-check parameter to process as if all files were present.")
            files = []
        else:
            files_in_dir = os.listdir(data_dir)

    total_rows_processed = 0

    for input_filename in input_filenames:
        with open(input_filename, 'r' , encoding='utf-8-sig') as input_file:
            print("..reading in from file: {}".format(input_filename))
            reader = csv.DictReader(input_file, delimiter = ',')
            row_counter = 1
            for row in reader:
                row_counter += 1
                row_type = row['TYPE'].lower().strip()
                if row_type == 'view':
                    this_row = View(row, row_counter)
                    this_row.validate_structure(objects, items)
                    this_row.validate_fields()
                    if this_row.value_issues or this_row.structural_issues:
                        continue
                    if not skip_file_check:
                        this_row.check_for_file(files_in_dir)
                    views[this_row.id] = this_row
                    this_row.check_for_self_in_drupal(media_in_drupal)

                elif row_type == 'item':
                    this_row = Item(row, row_counter)
                    this_row.validate_structure(objects, items)
                    this_row.validate_fields()
                    this_row.check_for_self_in_drupal(items_in_drupal)
                    this_row.check_for_self_in_drafts(drafts_in_drupal)
                    this_row.check_for_thumbnail(media_in_drupal)
                    items[this_row.id] = this_row

                elif row_type == 'object':
                    this_row = Object(row, row_counter)
                    this_row.validate_structure(objects, items)
                    this_row.validate_fields()
                    this_row.check_for_self_in_drupal(objects_in_drupal)
                    this_row.check_for_thumbnail(media_in_drupal)
                    objects[this_row.id] = this_row
                else:
                    print("WARNING: unknown row type: [{}] on line [{}]. Skipping row.".format(row_type, row_counter))

        total_rows_processed += row_counter


    ## PRINT REPORT
    print("..assessing results from input file.\n")
    print("Total rows: {}".format(total_rows_processed))
    stats = Analysis(objects, items, views)
    print_report(stats)

    obj_config = get_type_config("object")
    item_config = get_type_config("item")

    ## Options
    actions = [
        "OPTIONS AVAILABLE",
        "1. Create new objects and views ({} objects)".format(stats.new_objects_with_items),
        "2. Update 'draft' items ({} items)".format(stats.item_existing_drafts),
        "4. Update objects' thumbnails.",
        ""
        "5. Add metadata-only objects to Drupal (nodes only, without Views)",
        "3. Add available views to existing objects",
        "",
        "//4. Update existing objects' metadata",

        "",
    ]
    ## WHAT DO YOU WANT TO DO?
    print("\n")
    for line in actions:
        print(line)
    choice = input("What do you want to do? ")
    if choice == '':
        exit(0)
    print('-------------------------------------------------------------')
    timestamp = str(datetime.datetime.now().timestamp()).replace('.','_')
    import_config_url = creds['host'] + '/admin/config/development/configuration/single/import'
    media_add_url = creds['host'] + '/media/add/document'
    migration_url = creds['host'] + '/admin/structure/migrate/manage/october_27_archive/migrations'

    if choice == "1":
        print("1. Add new objects and views to Drupal.\n    - this will ignore Objects that don't have views available.\n        - this will likely create new stub (draft) Items.\n    - this will not add thumbnails to objects, those must be added separately.")
        filename = choice + "-new-objects-and-views.csv"
        config_filename = choice + "-workbench_conf.yml"
        filtered_objects, headers = prepare_objects_with_views(objects, views, new_objects=True, only_available_files=True)
        obj_config.update(dict(zip(headers, headers)))
        output_objects_as_csv(filename, filtered_objects, obj_config)
        print("Written file. # of objects: {}".format(len(filtered_objects)))
        headers.pop(0)
        output_workbench_config(config_filename, "create", filename, data_dir, additional_files=headers, allow_missing_files=True, nodes_only=False, id_field="field_object_identifier")

    if choice == "2":
        print("2. Update draft Items created by previous Object ingests. \n    - this will update thumbnails for the Items if available.")
        config_filename = choice + '-migration-config.yml'
        filtered_items = [ x for x in items.values() if x.is_draft ]
        filename = choice + "-update-item-drafts.csv"
        # Get headers config for items
        item_config.update({ 'id_in_drupal': 'tid' , "thumbnail_mid": "field_thumbnail"})
        output_objects_as_csv(filename, filtered_items, item_config)
        # get default migration yml
        migration_config  = read_in_yaml('conf' + os.sep + 'base_item_migration.yml')
        migration_config['label'] += ' - {}'.format(timestamp)
        migration_config['id'] += '_{}'.format(timestamp)
        with open(config_filename, 'w') as f:
            yaml.dump(migration_config, f)
        print("Please go to {} and upload the file {}".format(media_add_url, filename))
        print("Then, copy the file URL and correct the source path in the migration config in the file {}".format(config_filename))
        print("Then, go to {} and upload that migration config.".format(import_config_url))
        print("Finally, go to {} and execute the {} migration.".format(migration_url, migration_config['label']))



    if choice == "3":
        filename = choice + "-update-existing-objects-with-new-views"
        config_filename = choice+"-workbench_conf.yml"
        filtered_objects, headers = prepare_objects_with_views(objects, views, new_objects=False, only_available_files=True)
        obj_config = {'id_in_drupal': 'node_id'}
        obj_config.update(dict(zip(headers, headers)))
        output_objects_as_csv(filename, filtered_objects, obj_config)
        print("Written file. # of objects: {}".format(len(filtered_objects)))
        write_workbench_config(config_filename, "update", filename, data_dir,  additional_files=headers, allow_missing_files=False, nodes_only=False)

    if choice == "4":
        filename = choice + "-object-thumbnails.csv"
        config_filename = choice + '-workbench_conf.yml'
        filtered_objects = [x for x in objects.values() if (x.thumbnail_mid and x.id_in_drupal)]
        print(len(filtered_objects))
        obj_config = {"id_in_drupal": "node_id", "thumbnail_mid": "field_thumbnail" }
        output_objects_as_csv(filename, filtered_objects, obj_config)
        output_workbench_config(config_filename, "update", filename, data_dir, nodes_only=True)

    if choice == '5':
        print("5. Add new objects to drupal.\n    - this will ignore Objects already in drupal.\n    - this will not add any files (views)\n    - this may create new stub (draft) Items.")

        if stats.object_error_count > 0:
            print("There are errors in the objects that will cause Workbench to fail. Would you like to correct them now? ")
            go = input("[Y/n]")
            if go in ("yes", "y", "Yes", "Y", ""):
                print("Don't forget to save changes to the CSV file, not just the xslx. Re-run when ready.")
                exit(0)
        filename = choice + "-new-objects.csv"
        config_filename = choice + "-workbench_conf.yml"
        filtered_objects = [ obj for obj in objects.values() if obj.id_in_drupal == False ]
        obj_config['blank'] = 'file'
        output_objects_as_csv(filename, filtered_objects, obj_config)
        print("\nCreating migration file for {} objects.\n\n".format(len(filtered_objects)))
        output_workbench_config(config_filename, "create", filename, data_dir, nodes_only=True, id_field="field_object_identifier")


    if choice == "i":
        needle = input("Investigating. Enter an id.")
        if needle in objects.keys():
            print(objects[needle].values())
        elif needle in items.keys():
            print(items[needle])
        elif needle in views.keys():
            print(views[needle])

        # print("..loading field config for objects, views, and files.")
    #object_field_mapping, trash1, trash2, trash3 = get_config("object")
    #item_field_mapping, trash1, trash2, trash3 = get_config("item")
   # view_field_mapping, trash1, trash2, trash3 = get_config("view")

    # Make a thing to store them.
        # configs = {
    #     'item': '00-interim-items.csv',
    #     'object': '02-objects-to-ingest-with-workbench.csv',
    #     'view': '00-interim-views.csv',
    #     'name': '00-interim-names.csv',
    #     'thumbs_object': '00-interim-thumbs-objects.csv',
    #     'thumbs_item': '00-interim-thumbs-items.csv',
    #     'custom': '00-interim-custom.csv'}
    #
    #
    # for config in configs.keys():
    #
    #     # Get config
    #     field_mapping, dest_fieldnames, config_name, row_type = get_config(config)
    #
    #     # Open output file for this type.
    #     output_filename = configs[config]
    #
    #     if config_name == 'name':
    #         names = dict()
    #         with open(output_filename, 'r') as f: # Read in all names from the previous pass.
    #             reader = csv.DictReader(f, delimiter=',')
    #             for row in reader:
    #                 for header in row.keys():
    #                     if " KEY" not in header:
    #                         # this column designates a 'primary' (not sort key) name column. Consider all names.
    #                         raw_namestrings = row[header]
    #                         # Get accompanying key column, if present.
    #                         if header + " KEY" in row.keys():
    #                             raw_namekeystrings = row[header + " KEY"]
    #                         else:
    #                             raw_namekeystrings = ''
    #
    #                         # Split each into array by '|' separator
    #                         namestrings = raw_namestrings.split('|')
    #                         if raw_namekeystrings != '':
    #                             namekeystrings = raw_namekeystrings.split('|')
    #                         else:
    #                             namekeystrings = [''] * len(namestrings)
    #
    #                         if len(namestrings) != len(namekeystrings):
    #                             print("MULTIVALUE WARNING: Names and Name 'KEY's don't match. Names: [{}], Name keys: [{}]. These namekeys will not be entered.".format(raw_namestrings, raw_namekeystrings))
    #                         # Enter into the names dictionary.
    #                         for (name, namekey) in zip(namestrings, namekeystrings):
    #                             # Remove whitespace.
    #                             name = name.strip()
    #                             namekey = namekey.strip()
    #                             if name in names: # check for conflicts.
    #                                 if namekey == '':
    #                                   continue # If this row doesn't contain a namekey, we have no new info to add.
    #                                 elif names[name] == '':
    #                                   names[name] = namekey # We have a new namekey for name that previously didn't have one.
    #                                 elif names[name] != namekey:
    #                                   # Conflict between previously assigned namekey and this one.
    #                                   print("NAME KEY WARNING. [{}] offered as key for [{}], already assigned [{}].".format(namekey, name, names[name]))
    #                             else: # this is a new name
    #                                 names[name] = namekey
    #
    #         with open('01-names-preview.csv', 'w') as f: # Write out names for import.
    #             writer = csv.writer(f, delimiter = ',')
    #             writer.writerow(['CREATOR 1', 'CREATOR 1 KEY'])
    #             for name, namekey in sorted(names.items()):
    #                 if name == '':
    #                     continue # Don't include null name.
    #                 if namekey == '': # Don't include empty sortkeys, use the name value instead.
    #                     namekey = name
    #                 writer.writerow([name, namekey])

if __name__ == '__main__':
    main()

