#!/usr/bin/env python
import os
import csv
import importlib.util
from collections import namedtuple
from jinja2 import Template
import click


# Our data structures
version = 0.1

bulkextensions = []
failed_bulkextensions = []
failed_import_codes_struct = namedtuple('failed_import_codes_struct', 'dahdi notnumber other')
failed_code = failed_import_codes_struct('DAHDI Extension', 'Extension is not a number', 'Other, check line!')
failed_bulkextensions_reasons = []

extensions_columns = namedtuple('extensions_columns', 'action,extension,name,cid_masquerade,sipname,outboundcid,ringtimer,callwaiting,call_screen,pinless,password,noanswer_dest,noanswer_cid,busy_dest,busy_cid,chanunavail_dest,chanunavail_cid,emergency_cid,tech,hardware,devinfo_channel,devinfo_secret,devinfo_notransfer,devinfo_dtmfmode,devinfo_canreinvite,devinfo_context,devinfo_immediate,devinfo_signalling,devinfo_echocancel,devinfo_echocancelwhenbrdiged,devinfo_echotraining,devinfo_busydetect,devinfo_busycount,devinfo_callprogress,devinfo_host,devinfo_type,devinfo_nat,devinfo_port,devinfo_qualify,devinfo_callgroup,devinfo_pickupgroup,devinfo_disallow,devinfo_allow,devinfo_dial,devinfo_accountcode,devinfo_mailbox,devinfo_deny,devinfo_permit,devicetype,deviceid,deviceuser,description,dictenabled,dictformat,dictemail,langcode,record_in,record_out,vm,vmpwd,email,pager,attach,saycid,envelope,delete,options,vmcontext,vmx_state,vmx_unavail_enabled,vmx_busy_enabled,vmx_play_instructions,vmx_option_0_sytem_default,vmx_option_0_number,vmx_option_1_system_default,vmx_option_1_number,vmx_option_2_number,account,ddial,pre_ring,strategy,grptime,grplist,annmsg_id,ringing,grppre,dring,needsconf,remotealert_id,toolate_id,postdest,faxenabled,faxemail')


# Helper functions
def remove_garbage(text):
    return text.replace(' ', '_').replace('/', '_').replace('-', '_').lower().strip()


def validpass_generator(currentpass=None, zerofill=False, length=4, digitsonly=False):

    if currentpass == '':
        currentpass = None;

    import random, string
    if zerofill and currentpass is not None:
        return currentpass.zfill(length)
    else:
        if not digitsonly:
            return ''.join(random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(length))
        else:
            return ''.join(random.choice(string.digits) for _ in range(length))


def truthy(test):

    check = test.lower().strip()
    if check in ['enabled', 'yes', 'true', 'checked']:
        return True
    elif check.find('=yes') > -1:
        return True
    else:
        return False


def pretty_truthy(test):

    return 'Yes' if truthy(test) else 'No'


def pretty_ext(ext=None, comment=''):

    class extclass:
        def __init__(self):
            self.extension = 'Ext'
            self.name = 'Name'
            self.vm = 'VM'
            self.faxenabled = 'Fax'
            self.email = 'Email'
            self.devinfo_dtmfmode = 'DTMF'

    if ext == None:
        ext = extclass()

    print('{extension:>7} | {name:15} | {email:40} | {vm:3} | {fax:3} | {dtmf:5}'.format(extension=ext.extension, name=ext.name,
                                                        vm=pretty_truthy(ext.vm), fax=pretty_truthy(ext.faxenabled),
                                                        email=ext.email, dtmf=ext.devinfo_dtmfmode), end='')
    if comment:
        print(' >> %s' % comment)
    else:
        print()

# Main


def import_freepbx_csv(in_file, bypasscount):
    """
    This function is responsible for parsing the CSV generated by the FreePBX Bulk Extensions module.
    It should cover most situations as it essentially maps the header to a namedtuple and generates objects based on the
    namedtuple and adds them to the buklextensions global list.

    It also generates a failed_bulkextensions global list with the extensions that failed general parsing. For now the
    reasons to fail are if the extension is not SIP or IAX @TODO, and if the extension is not an int, or a catchall
    exception. The codes are appended to the failed_bulkextensions list.

    The function also prints the correctly parsed extensions, failed extensions as well as general stats.

    By default it throws an exception if the correct + failed extensions don't add up to the number of rows in the csv.
    """

    global bulkextensions, failed_bulkextensions, failed_code

    firstline = True
    pass_count = 0

    print('--- Extensions')
    pretty_ext()
    for ext in map(extensions_columns._make, csv.reader(open(in_file, "r"))):

        pass_count += 1

        # Header
        if firstline:
            firstline = False
            # bulkextensions[0] = ext
            continue

        # Only handle SIP/IAX, could potentially create DAHDIs but wouldn't know where to map them
        if ext.tech not in ['sip', 'iax']:
            failed_bulkextensions.append(ext)
            failed_bulkextensions_reasons.append(failed_code.dahdi)
            continue

        # If extension is not a valid number, skip
        try:
            int(ext.extension)
            bulkextensions.append(ext)
        except ValueError:
            failed_bulkextensions.append(ext)
            failed_bulkextensions_reasons.append(failed_code.notnumber)
            continue;
        except:
            failed_bulkextensions.append(ext)
            failed_bulkextensions_reasons.append(failed_code.other)

        pretty_ext(ext)


    print('\n--- Failed Extensions')
    pretty_ext()
    for ext, code in zip(failed_bulkextensions, failed_bulkextensions_reasons):
        pretty_ext(ext, code)

    print("\n--- Total Passes: %s | Imported Extensions: %s Failed Extensions: %s\n" % (pass_count, len(bulkextensions), len(failed_bulkextensions)))
    if not bypasscount:
        assert pass_count - 1 == len(failed_bulkextensions) + len(bulkextensions)


def export_ucm_csv(out_file, template, allrandom, prettyname, usefaxemail):
    """
    This function is responsible for exporting the extensions already parsed. It uses the mappings.py file as a template
    to import the mappings_header list which contains the proper header. Then it uses DictWriter to write rows of dicts.
    The dicts are generated from the same mappings.py. This time the mappings_template is first converted to str, then
    rendered via Jinja, then back to a new paython dict, and finally written as a row via the DictWriter object.

    The logic is also placed here, you can read through each line for the descriptions.
    """

    # Manually import mappings.py unless template is overridden, then load that
    spec = importlib.util.spec_from_file_location("mappings_template, mappings_header", template)
    tpl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tpl)


    with open(out_file, 'w') as csvfile:

        writer = csv.DictWriter(csvfile, fieldnames=tpl.mappings_header,)

        # Header
        writer.writeheader()

        for ext in bulkextensions:

            class ucmext_rec:
                pass
            ucmext = ucmext_rec()

            # Logic for fixing/parsing/mangling
            # Extension
            ucmext.extension = ext.extension

            # Name
            fullname = ext.name.title() if prettyname else ext.name

            try:
                ucmext.fname, ucmext.lname = fullname.split(' ')
            except:
                ucmext.fname, ucmext.lname = fullname, ''

            # DTMF
            ucmext.dtmf = ext.devinfo_dtmfmode.upper()

            # Outbound CID
            ucmext.outcid = "".join([c for c in ext.outboundcid if c.isdigit()])

            # Voicemail Yes/No
            ucmext.vm = 'yes' if truthy(ext.vm) else 'no'

            # Fax Yes/No
            ucmext.fax = 'Fax Detection' if truthy(ext.faxenabled) else ''

            # Email or if there is a Fax Email grab that just in case
            ucmext.email = ext.email.strip() if ext.email.strip() and usefaxemail else ext.faxemail.strip()

            zf_sip_pass = zf_vm_pass = not allrandom
            # Passwords (a min of 4 characters is required for sip and vm, and in addition digits and letters for user)
            ucmext.sip_pass = validpass_generator(ext.devinfo_secret, zf_sip_pass)
            ucmext.vm_pass = validpass_generator(ext.vmpwd, zf_vm_pass, digitsonly=True)
            ucmext.user_pass = validpass_generator(length=6, digitsonly=False)

            t = Template(str(tpl.mappings_template))
            rendered = t.render(ucm=ucmext)
            rendered_dict = eval(rendered)
            writer.writerow(rendered_dict)

@click.command()
@click.option('--template', type=click.Path(exists=True, dir_okay=False, readable=True, resolve_path=True),
              default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "mappings.py"),
              help='Uses a custom template file. Copy "mappings.py" and edit your own custom parameters.')
@click.option('--bypasscount', is_flag=True, default=False,
              help='Ignores failed import count check, make sure to visually inspect the parsed data first.')
@click.option('--allrandom', is_flag=True, default=False,
              help='Instead of padding the existing passwords with 0\'s, random passwords will be generated.')
@click.option('--prettyname', is_flag=True, default=False,
              help='Converts the extension name from e.g. FIRST LAST to First Last')
@click.option('--usefaxemail', is_flag=True, default=False,
              help='FreePBX has email and faxemail, UCM only has email, this option grabs faxemail if email doesn\'t exist')
@click.argument('freepbx_csv', type=click.Path(exists=True, dir_okay=False, readable=True, resolve_path=True))
@click.argument('ucm_csv_out', type=click.Path(writable=True, allow_dash=True), default='ucm_export.csv')
def cli(freepbx_csv, ucm_csv_out, template, bypasscount, allrandom, prettyname, usefaxemail):
    """
    This script converts (intelligently) between FreePBX's Bulk Extensions CSV and the Grandstream's UCM series CSV. It
    comes with a built-in template that maps FreePBX to the UCM's columns, while implementing logic to convert between
    the two different platforms. It has been tested on Grandstream's UCM6510 and pending other models for testing.

    \b
    Arguments:
    FREEPBX_CSV is the INPUT CSV file and it is required
    UCM_CSV_OUT is the OUTPUT CSV file, by default it exports to "ucm_export.csv"

    \b
    Notes:
    - Only processes SIP and IAX extensions (should be more than enough).
    - Deals with password requirements (enforced by the UCM software) in an
      automatic and opinionated way, altough this can be altered via options.
    - The built-in template can be overridden to include additional parameters.

    """
    import_freepbx_csv(freepbx_csv, bypasscount)
    export_ucm_csv(ucm_csv_out, template, allrandom, prettyname, usefaxemail)


if __name__ == '__main__':
    cli()
