import frappe

MEMORY = 'Relay Memory'


def execute():
    """Key Relay Memory rows by company and provider, taken from the channel of each row's last folded message.

    Rows without a message or channel keep empty values and are printed. The old unique key goes."""
    channels = {row.name: row for row in frappe.get_all('Relay Channel', fields=['name', 'company', 'channel'])}
    rows = frappe.get_all(MEMORY, filters={'provider': ['is', 'not set']}, fields=['name', 'last_message'])
    messages = dict(frappe.get_all('Relay Message', filters={'name': ['in', [row.last_message for row in rows]]},
                                   fields=['name', 'channel'], as_list=True)) if rows else {}
    unresolved = []
    for row in rows:
        channel = channels.get(messages.get(row.last_message))
        if channel:
            frappe.db.set_value(MEMORY, row.name, {'company': channel.company, 'provider': channel.channel},
                                update_modified=False)
        else:
            unresolved.append(row.name)
    if unresolved:
        print(f'Relay Memory rows without a channel kept their empty company and provider: {", ".join(unresolved)}')
    drop_old_key()


def drop_old_key():
    if frappe.conf.db_type == 'postgres':
        frappe.db.sql_ddl('ALTER TABLE "tabRelay Memory" DROP CONSTRAINT IF EXISTS relay_memory_period')
    elif frappe.db.has_index('tabRelay Memory', 'relay_memory_period'):
        frappe.db.sql_ddl('ALTER TABLE `tabRelay Memory` DROP INDEX relay_memory_period')
