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

## Run this script with an input file, a type, and -o outputfile.yml in order to extract objects from a spreadsheet.


def parse_cmd_line():
    parser = optparse.OptionParser(usage="%prog [options] INPUT_FILE")
#    parser.add_option("-t", "--type", dest="obj_type", default="all", help="Type to extract from spreadsheet. e.g. 'object'.")
    parser.add_option("-o", "--output", dest="output", default="O27-transformed", help="basename of output filename.") 
    opts, args = parser.parse_args()

    if len(args) < 1:
        parser.error("Need at least one input file on command line.")
    return opts.output, args

def get_config(conf_type):
    ## Get the config for this type (object, view, item)
    config_file = sys.path[0] + os.sep + 'conf' + os.sep + conf_type + '.yml'
    with open(config_file, 'r') as stream:
        try:
            object_config = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)
            exit(1)
    field_mapping = object_config['fields']
    dest_fieldnames = field_mapping.keys()
    conf_type = object_config['name']
    row_type = object_config['row_type']
    return field_mapping, dest_fieldnames, conf_type, row_type


def main():
    output_basename, input_filenames = parse_cmd_line()

    configs = {
        'object': '01-objects-to-ingest-with-workbench.csv',
        'item': 'interim-items.csv',
        'view': 'interim-views.csv',
        'name', 'interim-names.csv',
        'thumbs_objects': 'interim-thumbs-objects.csv',
        'thumbs_items': 'interim-thumbs-items.csv',
        'custom': 'interim-custom.csv'}

    for config in configs.keys:
        
        # Get config
        field_mapping, dest_fieldnames, config_name, row_type = get_config(config)
        
        # Open output file for this type.
        output_filename = configs[config]
        with open(output_filename, 'w') as f:
            writer = csv.writer(f, delimiter=',')
            ## Write header
            writer.writerow(dest_fieldnames)
            # Read through the spreadsheet file and create an output variant.
            for input_filename in input_filenames:
                with open(input_filename, 'r' , encoding='utf-8-sig') as input_file:
                    reader = csv.DictReader(input_file, delimiter = ',')
                    for row in reader:
                        ## Only get objects/views/items
                        if (row['TYPE'].lower() == row_type) or (row_type == 'all'):
                            #print([ row[field_mapping[a]] for a in dest_fieldnames])
                            raw = [ row[field_mapping[a]] for a in dest_fieldnames ]
                            # HACK FOR FILES WITHOUT EXTENSIONS
                            if config_name == 'view':
                                if raw[0] == '':
                                    print("VIEW NOT FOUND: no payload filename found for view for object [{}], in sheet [{}].".format(raw[1], input_filename)) 
                                    continue;
                                if raw[0][-4] != '.':
                                    raw[0] = raw[0] + '.jpg'
                            # HACK FOR THINGS WITHOUT TITLES
                            if config_name in ('item', 'object'):
                                if raw[0] == '':
                                    print("TITLE NEEDED: no title found for {} [{}].".format(row_type, raw[9]))
                                
                                    raw[0] = raw[9] # Position of 'ITEM' (id) in config. 
                            # HACK FOR SPECIFIC WRONG DATES
                            if config_name == 'object' and len(raw) > 8:
                                date = raw[9]
                                if '*' in date:
                                    print("BAD DATE ERROR - DATE NOT IMPORTED: [{}] is not a valid EDTF date in object [{}]. Use ~ at the end for approximate.".format(date, raw[0]) )
                                    raw[9] = ''
                                if '|' in date:
                                    print("BAD DATE ERROR - DATE NOT IMPORTED: [{}] - date field is not repeatable in object  [{}]".format(date, raw[0]) )
                                    raw[9] = ''
                                if "N/A" in date:
                                    print("BAD DATE WARNING: 'N/A' is redundant as a date, removing. ")
                                    raw[9] = ''
                                if '1909-1910' in date:
                                    print("BAD DATE ERROR - DATE NOT IMPORTED: [{}] is not a valid EDTF date in object [{}]. Use .. between ranges.".format(date, raw[0]) )
                                    raw[9] = ''
                            writer.writerow(raw)

        if config_name == 'name':
            names = dict()
            with open(output_filename, 'r') as f: # Read in all names from the previous pass.
                reader = csv.DictReader(f, delimiter=',')
                for row in reader:
                    for header in row.keys():
                        if " KEY" not in header:
                            # this column designates a 'primary' (not sort key) name column. Consider all names.
                            raw_namestrings = row[header]
                            # Get accompanying key column, if present.  
                            if header + " KEY" in row.keys():
                                raw_namekeystrings = row[header + " KEY"]
                            else:
                                raw_namekeystrings = ''

                            # Split each into array by '|' separator
                            namestrings = raw_namestrings.split('|')
                            if raw_namekeystrings != '':
                                namekeystrings = raw_namekeystrings.split('|')
                            else:
                                namekeystrings = [''] * len(namestrings)

                            if len(namestrings) != len(namekeystrings):
                                print("MULTIVALUE WARNING: Names and namekeys don't match. Names: [{}], Name keys: [{}]. These namekeys will not be entered.".format(raw_namestrings, raw_namekeystrings))
                            # Enter into the names dictionary.
                            for (name, namekey) in zip(namestrings, namekeystrings):
                                # Remove whitespace.
                                name = name.strip()
                                namekey = namekey.strip()
                                if name in names: # check for conflicts.
                                    if namekey == '':
                                      continue # If this row doesn't contain a namekey, we have no new info to add.
                                    elif names[name] == '':
                                      names[name] = namekey # We have a new namekey for name that previously didn't have one.
                                    elif names[name] != namekey:
                                      # Conflict between previously assigned namekey and this one.
                                      print("NAME KEY WARNING. [{}] offered as key for [{}], already assigned [{}].".format(namekey, name, names[name]))
                                else: # this is a new name
                                    names[name] = namekey

            with open('names-final.csv', 'w') as f: # Write out names for import.
                writer = csv.writer(f, delimiter = ',')
                writer.writerow(['CREATOR 1', 'CREATOR 1 KEY'])
                for name, namekey in sorted(names.items()):
                    if name == '':
                        continue # Don't include null name.
                    if namekey == '': # Don't include empty sortkeys, use the name value instead.
                        namekey = name
                    writer.writerow([name, namekey])
                

if __name__ == '__main__':
    main()

