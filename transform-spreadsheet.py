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
                print("NOTICE: Duplicate entries for {}: {} in file [{}]. {}: {}, {}".format(key_col, row[key_col], filename, val_col, data_dict[row[key_col]], row[val_col]))
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

def get_drupal_lookups(objects_file, media_file, item_file, name_file, host = ''):
    if os.path.isfile(objects_file):
        objects, key_errors = read_in_dict_file(objects_file, "field_object_identifier", "node_id")
        if 'blanks' in key_errors:
            print("ERROR in existing data: some objects are missing identifiers. Go here to fix:\n   {}/object-index".format(host))
        if 'dupes' in key_errors:
            print("ERROR in existing data: some objects have duplicate identifiers. Go here to fix:\n    {}/object-index".format(host))
        object_drafts = get_draft_items(objects_file,"field_object_identifier", "node_id","field_thumbnail")
    else:
        raise FileNotFoundError

    if os.path.isfile(media_file):
        media, media_key_errors = read_in_dict_file(media_file, "filename", "media_id")
        # # Hack for re-uploaded files, which get _0 appended to their filenames - I DONT KNOW WHAT TO DO HERE
        # for filename in media.keys():
        #     if filename.endswith("_0"):
        #         pass
    else:
        raise FileNotFoundError

    if os.path.isfile(item_file):
        items, item_key_errors = read_in_dict_file(item_file, "field_item_id", "term_id", silent=True)
        drafts = get_draft_items(item_file, "Name", "term_id", "field_item_id")
        dupes = set(items.keys()).intersection(set(drafts.keys()))
        if len(dupes) > 0:
            print("ERROR: Item 'drafts' duplicate existing Items that aren't drafts. [{}]".format(dupes))
    else:
        raise FileNotFoundError

    if os.path.isfile(name_file):
        names, name_key_errors = read_in_dict_file(name_file, "Name", "term_id")
        name_drafts = get_draft_items(name_file,"Name", "term_id", "field_sorting_name")
        if 'dupes' in name_key_errors:
            print("ERROR: Duplicate names in site. Go here to fix:\n    {}/term-index?vid=names".format(host))
    else:
        raise FileNotFoundError


    if len(key_errors) > 0 or len(media_key_errors) > 0 or ('dupes' in item_key_errors) or len(dupes) > 0 or len(name_key_errors) > 0:
        raise ValueError("Drupal data contains inconsistencies. Identifiers should be unique.")
    else:
        print("OK: Site contains {} objects.".format(len(objects)))
        print("OK: Site contains {} objects missing thumbnails.".format(len(object_drafts)))
        print("OK: Site contains {} media.".format(len(media)))
        print("OK: Site contains {} items.".format(len(items)))
        print("OK: Site contains {} draft items.".format(len(drafts)))
        print("OK: Site contains {} names.".format(len(names)))
        print("OK: Site contains {} draft names.".format(len(name_drafts)))

    return objects, media, items, drafts, names, name_drafts, object_drafts


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
    :return:
    """
    types = ['item','object','media','name']
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
    return "object_index.csv", "media_index.csv", "item_index.csv", "name_index.csv"


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
        self.is_draft = False
        self.structural_issues = False
        self.value_issues = False
        self.thumbnail_mid = False
        self.parent = False
        self.parent_id_in_drupal = False
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
            self.id_in_drupal = objects[self.id]
            return True
        else:
            return False

    def check_for_self_in_drafts(self, drafts):
        if self.id in drafts:
            self.id_in_drupal = drafts[self.id]
            self.is_draft = True
            return True
        else:
            return False

    def check_for_parent_in_drupal(self, things_in_drupal):
        if self.parent in things_in_drupal.keys():
            self.parent_id_in_drupal = things_in_drupal[self.parent]

    def check_for_thumbnail(self, media):
        if self.row["FILENAME"] in media.keys():
            self.thumbnail_mid = media[self.row["FILENAME"]]
            return True
        else:
            return False

    def validate_fields(self):

        # Check redacted.
        if self.row['REDACT'] != '':
            print("WARNING: Line {}. REDACT is not empty. Delete this row from the spreadsheet before proceeding.".format(self.row_number))
            self.value_issues = True
        # HACK FOR FILES WITHOUT EXTENSIONS
        if len(self.row["FILENAME"]) > 4:
            if self.row["FILENAME"][-4] != '.':
                self.row["FILENAME"] = self.row["FILENAME"] + '.jpg'


class Object(Row):
    def __init__(self, row, row_id = None):
        super().__init__(row, row_id)
        self.id = self.row["OBJECT"]
        self.row['id'] = self.id

    def values(self):
        values = super().values()
        if self.parent_id_in_drupal:
            values['ITEM'] = self.parent_id_in_drupal
        return values

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
        self.id = self.row["ITEM"]
        self.row['id'] = self.id


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
                print("ERROR: Row {}. Multiple matching files found in data dir: {} ".format(str(self.row_number),str(matches)))

class Name(Row):
    def __init__(self, row, row_id):
        super().__init__(row, row_id)
        self.id = row['NAME']
        self.is_draft = False

    def validate_structure(self, names):
        if self.id in names.keys():
            # This adds no new info
            if self.row['SORT KEY'] == '':
                pass # return something useless.
            elif self.row['SORT KEY'] == '':
                names[self.id].row['SORT KEY'] = self.row['SORT KEY']
                pass # also no new info!
            elif self.row['SORT KEY'] != names[self.id].row['SORT KEY']:
                self.structural_issues = True
                print("ERROR: conflicting sort names found for {}: [{}], [{}].".format(self.id, self.row['SORT KEY'],names[self.id].row['SORT KEY'] ))
            # This info conflict
        else:
            return self
            # This is good new info.

        # if self.row['SORT NAME'] == '':
        #     self.row['SORT NAME'] = self.id
        pass

    def values(self):
        values = super().values()
        if values['SORT KEY'] == '':
            values['SORT KEY'] = values['NAME']
        return values


class Analysis(object):
    def __init__(self, objects, items, views, names):
        self.object_count_total = len(objects.values())
        self.item_count_total = len(items.values())
        self.view_count_total = len(views.values())
        self.name_count_total = len(names.values())

        self.object_error_count = len([ x for x in objects.values() if (x.structural_issues or x.value_issues)])
        self.item_error_count = len([ x for x in items.values() if (x.structural_issues or x.value_issues)])
        self.view_error_count = len([ x for x in views.values() if (x.structural_issues or x.value_issues)])

        self.object_existing_total = len([ x for x in objects.values() if x.id_in_drupal ])
        self.item_existing_total = len([ x for x in items.values() if x.id_in_drupal ])
        self.view_existing_total = len([ x for x in views.values() if x.id_in_drupal ])

        self.item_existing_drafts = len([x for x in items.values() if x.is_draft])
        self.name_existing_drafts = len([x for x in names.values() if x.is_draft])
        self.object_existing_drafts = len([x for x in objects.values() if x.is_draft])

        self.view_has_file = len([ x for x in views.values() if x.has_file])
        self.new_view_has_file = len([ x for x in views.values() if x.has_file and not x.id_in_drupal])
        self.items_for_thumbs = len([x for x in items.values() if (x.thumbnail_mid and x.id_in_drupal)])

        self.objects_for_thumbs = len([x for x in objects.values() if (x.thumbnail_mid and x.id_in_drupal and x.is_draft)])
        new_objects = set([ x.id for x in objects.values() if not x.id_in_drupal ])
        self.new_objects_with_items = len(set([ x.parent for x in views.values() if x.has_file and x.parent in new_objects ]))




def print_report(stats):

    print("Total objects in spreadsheet: {}".format(stats.object_count_total))
    if stats.object_error_count > 0:
        print("  Objects with ERRORS: {}".format(stats.object_error_count))
    print("  New objects: {}".format(stats.object_count_total - stats.object_existing_total))
    print("  Objects already in Drupal: {}".format(stats.object_existing_total))

    print("Total items in spreadsheet: {}".format(stats.item_count_total))
    if stats.item_error_count > 0:
        print("  Items with ERRORS: {}".format(stats.item_error_count))
    print("  New items: {}".format(stats.item_count_total - stats.item_existing_total))
    print("  Items already in Drupal: {}".format(stats.item_existing_total))

    print("Total views in spreadsheet: {}".format(stats.view_count_total))
    if stats.view_error_count > 0:
        print("  Views with ERRORS: {}".format(stats.view_error_count))

    print("  Views already in Drupal: {}".format(stats.view_existing_total))
    print("  New view information: {}".format(stats.view_count_total - stats.view_existing_total))
    print("      Views with files to ingest: {}".format(stats.new_view_has_file))

    print("Total names in spreadsheet: {}".format(stats.name_count_total))

    print("Names in Drupal, needing updates (sort name): {} names".format(stats.name_existing_drafts))
    print("Objects in Drupal needing updates (thumbnails): {} objects".format(stats.objects_for_thumbs))
    print("Items in Drupal, needing updates (identifier): {} items".format(stats.item_existing_drafts))


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
        temp_object_list = [ obj for obj in all_objects.values() if obj.id_in_drupal != False ]

    for obj in temp_object_list:
        if only_available_files:
            children = [ x for x in views.values() if x.parent == obj.id and x.has_file and not x.id_in_drupal ]
        else:
            children = [ x for x in views.values() if x.parent == obj.id and not x.id_in_drupal]
        max_view_count = max([len(children), max_view_count])
    headers = ['file'] + [ "file_" + str(x) for x in range(max_view_count-1)]

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

def extract_names(row, name_fields):
    names = {}
    for header in name_fields.keys():
        if " KEY" not in header:
            # This column contains "primary" names (not sort names).
            raw_namestrings = row[header]
            # get accompanying key column, if present
            if header + " KEY" in row.keys():
                raw_namestrings_sort = row[header + " KEY"]
            else:
                raw_namestrings_sort = ''
            #split each into array by '|' separator
            namestrings = raw_namestrings.split('|')
            if raw_namestrings_sort != '':
                namestrings_sort = raw_namestrings_sort.split('|')
            else:
                namestrings_sort = [''] * len(namestrings)
            if len(namestrings) != len(namestrings_sort):
                print("ERROR: Multivalued fields {} and {} contain different numbers of entries.".format(raw_namestrings, raw_namestrings_sort))
                continue
            # Enter names into dictionary.
            for (name, sort_name) in zip(namestrings, namestrings_sort):
                # Remove whitespaces
                name = name.strip()
                sort_name = sort_name.strip()
                if name in names:
                    if sort_name == '':
                        continue # This row adds no additional info.
                    elif names[name] == '':
                        names[name] = sort_name # We have new information for a name that previously didn't have a sort key
                    elif names[name] != sort_name:
                        # Conflict between previously assigned name key and this one.
                        print("ERROR: Two different sort names offered for {}. [{}] and [{}].".format(name, names[name], sort_name))
                else:
                    names[name] = sort_name
    return names


def output_workbench_config(filename, task, input_csv, input_dir, additional_files = None, **options):
    write_workbench_config(filename, task, input_csv, input_dir, additional_files, **options)
    print("Use the following argument for workbench:\n  --config {} --check\n".format( os.path.abspath(filename)))

def write_workbench_config(filename, task, input_csv, input_dir, additional_files = None, **options  ):
    data = {}
    data['task'] = task
    data.update(get_workbench_creds())
    data['input_csv'] =  os.path.abspath(input_csv)
    data['input_dir'] =  os.path.abspath(input_dir)
    data.update(options)
    data.update(read_in_yaml('conf'+ os.sep + 'base_workbench_config.yml'))

    if additional_files:
        data['additional_files'] = [ {x: 5} for x in additional_files] # 5 is the term id of "Service File"
    with(open(filename, 'w')) as f:
        doc = yaml.dump(data,f, sort_keys = False, default_style = '"')

def main():
    data_dir, skip_file_check, input_filenames = parse_cmd_line()

    # List of files in data-dir
    files_in_dir = []
    if not skip_file_check:
        print("Checking for files in data directory.")
        if not os.path.isdir(data_dir):
            print("WARNING: Data directory not available. Provide the path to the files in the --data-dir parameter. It will not be possible to create configurations to upload files. ")
            skip_file_check = True
        else:
            files_in_dir = os.listdir(data_dir)
            print("OK: data directory contains {} files.\n".format(len(files_in_dir)))



    # TODO: make optional, to process structure of file alone.
    # Get data about existing objects, media, names, and items.
    try:
        print("Validating items, objects and views in Drupal.")
        creds = get_workbench_creds()

        # TODO: refactor this to use JSON instead of writing to CSV files.
        object_index_filename, media_index_filename, item_index_filename, name_index_filename = update_csv_indexes(creds)
        objects_in_drupal, media_in_drupal, items_in_drupal, drafts_in_drupal, names_in_drupal, name_drafts_in_drupal, objects_missing_thumbs = get_drupal_lookups(object_index_filename, media_index_filename, item_index_filename, name_index_filename, creds['host'])

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
    else:
        objects = {}
        items = {}
        views = {}
        names = {}
        name_fields = read_in_yaml('conf' + os.sep + 'name.yml')

        total_rows_processed = 0

        for input_filename in input_filenames:
            with open(input_filename, 'r' , encoding='utf-8-sig') as input_file:
                print("\nReading in from file: {}".format(input_filename))
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
                        this_row.check_for_self_in_drupal(media_in_drupal)
                        this_row.check_for_parent_in_drupal(objects_in_drupal)
                        views[this_row.id] = this_row

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
                        this_row.check_for_self_in_drafts(objects_missing_thumbs)
                        this_row.check_for_parent_in_drupal(items_in_drupal)
                        this_row.check_for_thumbnail(media_in_drupal)
                        objects[this_row.id] = this_row
                    else:
                        print("WARNING: unknown row type: [{}] on line [{}]. Skipping row.".format(row_type, row_counter))
                    names_from_this_row = extract_names(row, name_fields)
                    for name in names_from_this_row.keys():
                        this_name = Name({'NAME': name,'SORT KEY': names_from_this_row[name]},row_counter)
                        this_name.check_for_self_in_drupal(names_in_drupal)
                        this_name.check_for_self_in_drafts(name_drafts_in_drupal)
                        this_name.validate_structure(names)
                        names[this_name.id] = this_name

            total_rows_processed += row_counter


        ## PRINT REPORT
        print("\nAssessing results from input files.\n")
        print("Total rows: {}".format(total_rows_processed))
        stats = Analysis(objects, items, views, names)
        print_report(stats)

        obj_config = get_type_config("object")
        item_config = get_type_config("item")

        ## Options
        actions = [
            "OPTIONS AVAILABLE",
            "1. Create new objects with views ({} objects)".format(stats.new_objects_with_items),
            "2. Update objects missing thumbnails ({} objects).".format(stats.objects_for_thumbs),
            "3. Update 'draft' items ({} items)".format(stats.item_existing_drafts),
            "4. Update 'draft' names ({} names)".format(stats.name_existing_drafts),
            "",
            "5. Add metadata-only objects to Drupal (nodes only, without Views) ({} objects)".format(stats.object_count_total - stats.object_existing_total),
            "6. Add available views to existing objects",
            "7. Preview names in spreadsheet.",
            "",
            "i. investigate an object by its id.",
            "<enter> to exit.",
        ]
        # WHAT DO YOU WANT TO DO?
        print("\n")
        for line in actions:
            print(line)

        while True:
            choice = input("What do you want to do? ")
            if choice in (['1','2','3','4','5', '6', '7','i','']):
                break
        if choice == '':
            exit(0)
        print('-------------------------------------------------------------')
        items_feed = creds['host'] + "/feed/1/edit"
        names_feed = creds['host'] + '/feed/3/edit'
        migration_url = creds['host'] + '/admin/structure/migrate/manage/october_27_archive/migrations'
        feeds = False

        if choice == "1":
            print("1. Add new objects and views to Drupal.\n    - this will ignore Objects that don't have views available.\n    - this will likely create new stub (draft) Items.\n    - this will not add thumbnails to objects, those must be added in a subsequent operation.")

            # Write CSV file.
            filename = choice + "-new-objects-and-views.csv"
            filtered_objects, headers = prepare_objects_with_views(objects, views, new_objects=True, only_available_files=True)
            obj_config.update(dict(zip(headers, headers)))
            obj_config['id'] = 'id'
            output_objects_as_csv(filename, filtered_objects, obj_config)
            print("Written file. # of objects: {}\n".format(len(filtered_objects)))

            # Write workbench config.
            config_filename = choice + "-workbench_conf.yml"
            headers.pop(0) # Necessary to remove 'file' (first entry) from additional_files.
            #output_workbench_config(config_filename, "create", filename, data_dir, additional_files=headers, allow_missing_files=True, nodes_only=False, id_field="field_object_identifier")
            output_workbench_config(config_filename, "create", filename, data_dir, additional_files=headers, allow_missing_files=True, nodes_only=False) # Mark pushed some changes that broke taxonomy when he fixed the id_field.

        if choice == "2":
            print(choice + ". Provide thumbnails for objects missing thumbnails.")
            filename = choice + "-object-thumbnails.csv"
            config_filename = choice + '-workbench_conf.yml'
            filtered_objects = [x for x in objects.values() if (x.thumbnail_mid and x.id_in_drupal and x.is_draft)]
            obj_config = {"id_in_drupal": "node_id", "thumbnail_mid": "field_thumbnail" }
            output_objects_as_csv(filename, filtered_objects, obj_config)
            print("Written file. # of objects: {}\n".format(len(filtered_objects)))
            output_workbench_config(config_filename, "update", filename, data_dir, nodes_only=True)

        if choice == "3":
            print(choice + ". Update draft Items created by previous Object ingests. \n    - this will update thumbnails for the Items if available.")
            # Write out CSV file.
            filename = choice + "-update-item-drafts.csv"
            filtered_items = [ x for x in items.values() if x.is_draft ]
            item_config.update({ 'id_in_drupal': 'tid' , "thumbnail_mid": "field_thumbnail"})
            output_objects_as_csv(filename, filtered_items, item_config)

            print("\n  Item file: {}".format(filename))
            print("Please go to {} and replace the file with {}".format(items_feed, filename))

        if choice == "4":
            print(choice + " - Updating existing names that are drafts (missing sort field).")

            # Write out csv file
            filename = choice + "-update-draft-names.csv"
            filtered_names = [ x for x in names.values() if x.is_draft]
            name_config = {'id_in_drupal': 'tid', 'NAME': 'name', 'SORT KEY': 'field_sorting_name'}
            output_objects_as_csv(filename, filtered_names, name_config)

            print("\n  Names CSV file: {}\n".format(filename))
            print("Please go to {} and replace the file with {}".format(names_feed, filename))


        if choice == '5':
            print("5. Add new objects to drupal.\n    - this will ignore Objects already in drupal.\n    - this will not add any files (views)\n    - this may create new stub (draft) Items.")
            # Write CSV file
            filename = choice + "-new-objects.csv"
            filtered_objects = [ obj for obj in objects.values() if obj.id_in_drupal == False ]
            obj_config['blank'] = 'file'
            obj_config['id'] = 'id'
            output_objects_as_csv(filename, filtered_objects, obj_config)
            print("\nCreating migration file for {} objects.\n\n".format(len(filtered_objects)))

            # Write workbench config
            config_filename = choice + "-workbench_conf.yml"
            output_workbench_config(config_filename, "create", filename, data_dir, nodes_only=True)
            #output_workbench_config(config_filename, "create", filename, data_dir, nodes_only=True, id_field="field_object_identifier")


        if choice == "6":
            print("6. Adding new Views to existing Objects.")

            # Write CSV file.
            filename = choice + "-update-existing-objects-with-new-views.csv"
            filtered_objects = [ x for x in views.values() if x.has_file and x.parent_id_in_drupal != False and not x.id_in_drupal ]
            obj_config = {'parent_id_in_drupal': 'node_id', 'id': 'file'}
            output_objects_as_csv(filename, filtered_objects, obj_config)
            print("Written file. # of objects: {}\n".format(len(filtered_objects)))

            # Write workbench config.
            config_filename = choice+"-workbench_conf.yml"
            output_workbench_config(config_filename, "add_media", filename, data_dir, allow_missing_files=False, nodes_only=False)

        if choice == '7':
            print("7. Previewing names in the spreadsheet.")
            filename = choice + '-names-preview.csv'
            filtered_names = [ x for x in names.values() ]
            obj_config = {'NAME': 'NAME', 'SORT KEY': 'SORT KEY'}
            output_objects_as_csv(filename, filtered_names, obj_config)
            print("Written file. # of names: {}\n".format(len(filtered_names)))
            print("\nPlease review the file: {}".format(filename))

        if choice == "i":
            needle = input("Investigating. Enter an id.")
            if needle in objects.keys():
                print(objects[needle].values())
            elif needle in items.keys():
                print(items[needle].values())
            elif needle in views.keys():
                print(views[needle].values())



if __name__ == '__main__':
    main()

