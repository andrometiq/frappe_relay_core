import json

import click
from frappe.commands import get_site, pass_context


@click.command('relay-import-whatsapp-core')
@click.option('--source-db', help='Source database name. Leave out to read this site\'s own WhatsApp Core tables.')
@click.option('--source-host', help='Source database host (default: this site\'s host).')
@click.option('--source-port', type=int, help='Source database port.')
@click.option('--source-user', default='root', show_default=True, help='Source database user.')
@click.option('--source-password-file', help='File with the source password (else RELAY_SOURCE_DB_PASSWORD).')
@click.option('--source-site-label', required=True, help='Stable name of the old site, such as sales.essdee.fit. Part of each message\'s import key.')
@click.option('--channel', 'channels', multiple=True, help='SOURCE_CHANNEL=RELAY_CHANNEL; repeat per source channel.')
@click.option('--files-dir', help='Directory with the old private files; media found here are copied, others are linked as is.')
@click.option('--batch', default=2000, show_default=True, help='Messages per insert.')
@click.option('--dry-run', is_flag=True, help='Count only; write nothing.')
@click.option('--undo', is_flag=True, help='Delete what the import with this --source-site-label created.')
@pass_context
def relay_import_whatsapp_core(context, source_db, source_host, source_port, source_user, source_password_file,
                               source_site_label, channels, files_dir, batch, dry_run, undo):
    """Import frappe_whatsapp_core messages into Relay. Safe to re-run: imported messages are skipped."""
    import frappe

    from relay_core import legacy_database

    channel_map = dict(item.split('=', 1) for item in channels)
    frappe.init(get_site(context))
    frappe.connect()
    frappe.set_user('Administrator')
    frappe.flags.mute_emails = True
    if undo:
        click.echo(json.dumps(legacy_database.undo(source_site_label), indent=1))
        frappe.destroy()
        return
    source = legacy_database.Source(source_db, source_host, source_port, source_user,
                    legacy_database.source_password(source_password_file) if source_db else None)
    try:
        started = frappe.utils.now_datetime()
        result = legacy_database.Importer(source, source_site_label, channel_map, batch, dry_run, files_dir).run()
        result['seconds'] = round((frappe.utils.now_datetime() - started).total_seconds(), 1)
        result['dry_run'] = dry_run
        click.echo(json.dumps(result, indent=1, default=str))
    finally:
        source.close()
        frappe.destroy()


commands = [relay_import_whatsapp_core]
