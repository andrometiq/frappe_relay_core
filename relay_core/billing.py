"""WhatsApp billing: Meta pricing analytics cached per month, with a margin and Relay send counts."""
import hashlib
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import frappe
from relay_core.hub import HubError
from relay_core.permissions import require_access
from relay_core.settings import value as connection_value

DOCTYPE = 'Relay WhatsApp Billing Month'
DEFAULT_MARGIN = 30.0
DIMENSIONS = ['PRICING_CATEGORY', 'PRICING_TYPE']
SENT = ('Sent', 'Delivered', 'Read')


def site_zone():
    return ZoneInfo(frappe.utils.get_system_timezone())


def valid_year(year):
    try:
        year = int(year)
    except (TypeError, ValueError):
        frappe.throw('Year must be a number')
    if not 2020 <= year <= 2100:
        frappe.throw('Year must be between 2020 and 2100')
    return year


def year_bounds(year, now=None):
    """UNIX seconds of the site-timezone year, ending at now for the current year."""
    zone = site_zone()
    start = datetime(year, 1, 1, tzinfo=zone)
    end = min(datetime(year + 1, 1, 1, tzinfo=zone), now or datetime.now(zone))
    return int(start.timestamp()), int(end.timestamp())


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def label(value):
    text = str(value or '').strip().upper()[:60]
    return text or 'UNKNOWN'


def period_of(point):
    """First day of the bucket's month in the site timezone. The bucket midpoint is safe for any UTC offset."""
    start = number(point.get('start'))
    end = number(point.get('end')) or start
    return datetime.fromtimestamp((start + end) / 2, site_zone()).date().replace(day=1)


def parse(points):
    """Meta data points -> {(period, category, pricing_type): totals}. Field names are read defensively."""
    rows = {}
    for point in points:
        if not isinstance(point, dict) or number(point.get('start')) <= 0:
            continue
        key = (period_of(point), label(point.get('pricing_category')), label(point.get('pricing_type')))
        row = rows.setdefault(key, {'volume': 0, 'meta_cost': 0.0, 'currency': '', 'raw': []})
        row['volume'] += int(number(point.get('volume')))
        row['meta_cost'] += number(point.get('cost'))
        row['currency'] = row['currency'] or str(point.get('currency') or '')[:10]
        row['raw'].append(point)
    return rows


def record_key(identity):
    """Deterministic, so concurrent refreshes of one key update a single row."""
    return 'RWB-' + hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()[:20]


def upsert(account, key, values, fetched_at):
    period, category, pricing_type = key
    identity = {'account': account, 'period': period, 'category': category, 'pricing_type': pricing_type}
    fields = {'volume': values['volume'], 'meta_cost': round(values['meta_cost'], 6), 'currency': values['currency'],
              'fetched_at': fetched_at, 'raw_data': json.dumps(values['raw'], sort_keys=True, default=str)}
    name = record_key(identity)
    if not frappe.db.exists(DOCTYPE, name):
        try:
            return insert({'doctype': DOCTYPE, 'record_key': name, **identity, **fields})
        except frappe.DuplicateEntryError:
            pass
    frappe.db.set_value(DOCTYPE, name, fields)


def insert(values):
    previous = getattr(frappe.flags, 'relay_automation_internal', False)
    frappe.flags.relay_automation_internal = True
    try:
        frappe.get_doc(values).insert(ignore_permissions=True)
    finally:
        frappe.flags.relay_automation_internal = previous


def configured_account(account):
    if not isinstance(account, str) or account != connection_value('relay_hub_account'):
        frappe.throw('Billing can be read from Meta only for the configured Hub account')
    return account


def refresh(account, year):
    """Read the year's monthly Meta charges through the Hub and upsert one row per month, category and type."""
    from relay_core.whatsapp import checked_client
    year, account = valid_year(year), configured_account(account)
    start, end = year_bounds(year)
    if end <= start:
        return {'rows': 0, 'data_points': 0}
    hub, _ = checked_client()
    result = hub.execute({'operation': 'billing.pricing', 'start': start, 'end': end,
                          'granularity': 'MONTHLY', 'dimensions': DIMENSIONS})
    points = result.get('data_points') if isinstance(result, dict) else None
    if not isinstance(points, list):
        raise HubError('Hub returned no pricing data points')
    rows, fetched_at = parse(points), frappe.utils.now_datetime()
    for key, values in rows.items():
        upsert(account, key, values, fetched_at)
    return {'rows': len(rows), 'data_points': len(points)}


def refresh_configured():
    """Daily: refresh this year, and last year during the first week of January."""
    account = connection_value('relay_hub_account')
    if not account or not frappe.db.exists('Relay Channel', {'channel': 'WhatsApp', 'account': account, 'enabled': 1}):
        return
    today = frappe.utils.getdate()
    for year in sorted({today.year, (today - timedelta(days=7)).year}):
        try:
            refresh(account, year)
            frappe.db.commit()
        except (HubError, ValueError, frappe.ValidationError):
            frappe.db.rollback()
            frappe.log_error(title='Relay WhatsApp billing refresh failed')


def margin_percent():
    """Unset means the default; an explicit 0 stays 0."""
    rows = frappe.db.sql("SELECT value FROM `tabSingles` WHERE doctype='Relay Settings' AND field='whatsapp_margin_percent'")
    value = rows[0][0] if rows else None
    return DEFAULT_MARGIN if value in (None, '') else number(value)


def priced(volume, meta_cost, margin):
    meta_cost = float(meta_cost or 0)
    margin_amount = round(meta_cost * margin / 100, 4)
    return {'volume': int(volume), 'meta_cost': round(meta_cost, 4), 'margin_amount': margin_amount,
            'total': round(meta_cost + margin_amount, 4)}


def account_channels(account):
    """WhatsApp channels of the account that the caller may read; none means no access."""
    if not isinstance(account, str) or not 1 <= len(account) <= 100:
        frappe.throw('Account is required')
    channels = frappe.get_list('Relay Channel', filters={'channel': 'WhatsApp', 'account': account}, pluck='name')
    if not channels:
        frappe.throw('WhatsApp account is not accessible', frappe.PermissionError)
    return channels


def message_counts(channels, year):
    """Outgoing WhatsApp messages per site-timezone month, and per template and month."""
    window = {'channels': tuple(channels), 'sent': SENT, 'start': datetime(year, 1, 1), 'end': datetime(year + 1, 1, 1)}
    where = ("FROM `tabRelay Message` WHERE channel IN %(channels)s AND direction='Outgoing' "
             "AND status IN %(sent)s AND sent_at >= %(start)s AND sent_at < %(end)s")
    months = dict(frappe.db.sql(f"SELECT MONTH(sent_at), COUNT(*) {where} GROUP BY MONTH(sent_at)", window))
    templates = frappe.db.sql(
        "SELECT template, month, COUNT(*) FROM (SELECT JSON_UNQUOTE(JSON_EXTRACT(message_data, '$.template.name')) "
        f"template, MONTH(sent_at) month {where}) sends WHERE template IS NOT NULL GROUP BY template, month", window)
    return months, templates


def template_categories(account, names):
    if not names:
        return {}
    rows = frappe.get_all('Relay WhatsApp Template', filters={'account': account, 'template_name': ['in', list(names)]},
                          fields=['template_name', 'category'])
    return {row.template_name: row.category for row in rows}


def billing_rows(account, year):
    return frappe.get_all(DOCTYPE, filters={'account': account, 'period': ['between', [date(year, 1, 1), date(year, 12, 31)]]},
                          fields=['period', 'category', 'pricing_type', 'volume', 'meta_cost', 'currency', 'fetched_at'],
                          order_by='period asc, category asc, pricing_type asc', limit_page_length=0)


def add(total, volume, meta_cost):
    total['volume'] += volume or 0
    total['meta_cost'] += meta_cost or 0


def summarise(year, rows, months_sent, margin):
    """Twelve months with their category rows, yearly category totals and the year total."""
    months = {month: {'period': str(date(year, month, 1)), 'messages_sent': int(months_sent.get(month, 0)),
                      'categories': [], 'volume': 0, 'meta_cost': 0.0} for month in range(1, 13)}
    categories = {}
    for row in rows:
        month = months[frappe.utils.getdate(row.period).month]
        month['categories'].append({'category': row.category, 'pricing_type': row.pricing_type,
                                    **priced(row.volume or 0, row.meta_cost or 0, margin)})
        add(month, row.volume, row.meta_cost)
        add(categories.setdefault(row.category, {'volume': 0, 'meta_cost': 0.0}), row.volume, row.meta_cost)
    ordered = [{**month, **priced(month['volume'], month['meta_cost'], margin)} for month in months.values()]
    total = priced(sum(m['volume'] for m in ordered), sum(m['meta_cost'] for m in ordered), margin)
    total['messages_sent'] = sum(m['messages_sent'] for m in ordered)
    by_category = [{'category': name, **priced(value['volume'], value['meta_cost'], margin)}
                   for name, value in sorted(categories.items())]
    return ordered, by_category, total


@frappe.whitelist(methods=['GET'])
def get_billing(account, year):
    """Meta charges per month and category with the margin, plus Relay send counts per month and template."""
    require_access(manage=True)
    year, channels = valid_year(year), account_channels(account)
    margin, rows = margin_percent(), billing_rows(account, year)
    months_sent, template_rows = message_counts(channels, year)
    months, categories, total = summarise(year, rows, months_sent, margin)
    names = {row[0] for row in template_rows}
    category_of = template_categories(account, names)
    templates = [{'template': name, 'category': category_of.get(name) or '', 'period': str(date(year, month, 1)),
                  'messages_sent': count} for name, month, count in template_rows]
    return {'account': account, 'year': year, 'margin_percent': margin,
            'currency': next((row.currency for row in rows if row.currency), ''),
            'fetched_at': str(max(row.fetched_at for row in rows)) if rows else None,
            'months': months, 'categories': categories, 'templates': templates, 'total': total}


@frappe.whitelist(methods=['POST'])
def refresh_billing(account, year):
    """Manager-triggered Meta read for one account and year."""
    from relay_core.whatsapp import failure_message
    require_access(manage=True)
    account_channels(account)
    try:
        return refresh(account, year)
    except (HubError, ValueError) as error:
        frappe.throw(failure_message(error))
