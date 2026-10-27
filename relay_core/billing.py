"""WhatsApp billing: Meta pricing cached per month, billed to the customer with the service charge in the rate."""
import hashlib
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import frappe
from relay_core.hub import HubError
from relay_core.hub_channels import hub_arguments
from relay_core.permissions import require_access, can_configure
from relay_core.settings import value as connection_value

DOCTYPE = 'Relay WhatsApp Billing Month'
DEFAULT_MARGIN = 30.0
DIMENSIONS = ['PRICING_CATEGORY', 'PRICING_TYPE']
CHANNEL_FIELDS = ['name', 'channel', 'account', 'hub_channel', 'label', 'address', 'waba_id']
SENT = ('Sent', 'Delivered', 'Read')
PAID_ORDER = ['MARKETING', 'UTILITY', 'AUTHENTICATION']


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


def parse(points, currency=''):
    """Meta data points -> {(period, category, pricing_type): totals}. Field names are read defensively; a point
    without a currency takes the WABA currency."""
    rows = {}
    for point in points:
        if not isinstance(point, dict) or number(point.get('start')) <= 0:
            continue
        key = (period_of(point), label(point.get('pricing_category')), label(point.get('pricing_type')))
        row = rows.setdefault(key, {'volume': 0, 'meta_cost': 0.0, 'currency': '', 'raw': []})
        row['volume'] += int(number(point.get('volume')))
        row['meta_cost'] += number(point.get('cost'))
        row['currency'] = row['currency'] or str(point.get('currency') or currency)[:10]
        row['raw'].append(point)
    return rows


def record_key(identity):
    """Deterministic, so concurrent refreshes of one key update a single row."""
    return 'RWB-' + hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()[:20]


def owner(account, channel, waba=''):
    """Extra identity and link fields of a row. `channel` None means charges Meta did not split per number.
    The legacy channel, keyed by the account id, keeps the account-wide identity so its rows update in place."""
    if channel is None:
        return {'channel': '', 'waba': waba}, {'relay_channel': None, 'unsplit': 1}
    keyed = channel.hub_channel and channel.hub_channel != account
    return ({'channel': channel.hub_channel} if keyed else {}), {'relay_channel': channel.name, 'unsplit': 0}


def upsert(account, key, values, fetched_at, channel=None, waba=''):
    period, category, pricing_type = key
    extra, link = owner(account, channel, waba)
    identity = {'account': account, 'period': period, 'category': category, 'pricing_type': pricing_type}
    phone = next((str(point['phone_number'])[:40] for point in values['raw'] if point.get('phone_number')), '')
    fields = {'volume': values['volume'], 'meta_cost': round(values['meta_cost'], 6), 'currency': values['currency'],
              'fetched_at': fetched_at, 'raw_data': json.dumps(values['raw'], sort_keys=True, default=str),
              'phone_number': phone, **link}
    identity_key = dict(identity, **extra)
    name = record_key(identity_key)
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


def pricing(hub, request):
    result = hub.execute(request)
    points = result.get('data_points') if isinstance(result, dict) else None
    if not isinstance(points, list):
        raise HubError('Hub returned no pricing data points')
    return points, result.get('currency') if isinstance(result.get('currency'), str) else ''


def digits(value):
    return ''.join(character for character in str(value or '') if character.isdigit())


def point_channel(point, channels):
    """The number a data point belongs to: the Hub's channel key first, then Meta's phone number.
    None means Meta did not split the charge per number, or named a number this site does not own."""
    if not isinstance(point, dict):
        return None
    key, phone = point.get('channel_key'), digits(point.get('phone_number'))
    return next((channel for channel in channels if (key and channel.hub_channel == key)
                 or (not key and phone and digits(channel.address) == phone)), None)


def billing_channels(account):
    """Enabled WhatsApp channels of the account, grouped per WABA; one Meta read covers each WABA."""
    rows = frappe.get_all('Relay Channel', fields=CHANNEL_FIELDS, order_by='is_default desc, creation asc',
                          filters={'account': account, 'channel': 'WhatsApp', 'enabled': 1})
    wabas = {}
    for row in rows:
        wabas.setdefault(row.waba_id or '', []).append(row)
    return wabas, len(rows) > 1


def refresh(account, year):
    """Read the year's monthly Meta charges and the WABA currency through the Hub, and upsert one row per number,
    month, category and type. A site with one number keeps the request of a single-number Hub."""
    from relay_core.whatsapp import checked_client
    year, account = valid_year(year), configured_account(account)
    start, end = year_bounds(year)
    if end <= start:
        return {'rows': 0, 'data_points': 0}
    wabas, split = billing_channels(account)
    if not wabas:
        frappe.throw('Configure an enabled WhatsApp channel')
    hub, _ = checked_client()
    request = {'operation': 'billing.pricing', 'start': start, 'end': end, 'granularity': 'MONTHLY', 'dimensions': DIMENSIONS}
    fetched_at, rows, read = frappe.utils.now_datetime(), 0, 0
    for waba, channels in wabas.items():
        points, currency = pricing(hub, hub_arguments(channels[0], dict(request, dimensions=['PHONE', *DIMENSIONS]))
                                   if split else request)
        groups, by_name = {}, {channel.name: channel for channel in channels}
        for point in points:
            channel = point_channel(point, channels) if split else channels[0]
            groups.setdefault(channel and channel.name, []).append(point)
        for name, channel_points in groups.items():
            parsed = parse(channel_points, currency)
            for key, values in parsed.items():
                upsert(account, key, values, fetched_at, by_name.get(name), waba)
            rows += len(parsed)
        read += len(points)
    return {'rows': rows, 'data_points': read}


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


@frappe.whitelist(methods=['GET'])
def get_margin():
    require_access(configure=True)
    return {'margin_percent': margin_percent()}


@frappe.whitelist(methods=['POST'])
def save_margin(percent):
    """System Manager only; Relay Settings validates the 0-1000 range."""
    require_access(configure=True)
    try:
        percent = float(percent)
    except (TypeError, ValueError):
        frappe.throw('Margin percent must be a number')
    settings = frappe.get_single('Relay Settings')
    settings.whatsapp_margin_percent = percent
    settings.save()
    return {'margin_percent': margin_percent()}


def bill_category(category, pricing_type):
    """Free messages (service window, free entry points) bill as SERVICE; paid ones keep their Meta category."""
    return 'SERVICE' if category == 'SERVICE' or str(pricing_type).startswith('FREE') else category


def category_order(category):
    return (category == 'SERVICE', PAID_ORDER.index(category) if category in PAID_ORDER else len(PAID_ORDER), category)


def billed_rate(volume, meta_cost, margin):
    """Charge per message: Meta's average cost per message with the service charge added."""
    if not volume or not meta_cost:
        return 0.0
    return round(meta_cost / volume * (1 + margin / 100), 4)


def bill_line(category, volume, meta_cost, margin):
    rate = billed_rate(volume, meta_cost, margin)
    return {'category': category, 'messages': int(volume), 'rate': rate, 'amount': round(rate * volume, 2)}


def statement(lines):
    """Messages and amount of a set of bill lines; the amount is the sum of the rounded line amounts."""
    return {'messages': sum(line['messages'] for line in lines), 'amount': round(sum(line['amount'] for line in lines), 2)}


def month_bill(period, rows, margin):
    grouped = {}
    for row in rows:
        totals = grouped.setdefault(bill_category(row.category, row.pricing_type), [0, 0.0])
        totals[0] += row.volume or 0
        totals[1] += row.meta_cost or 0
    lines = [bill_line(category, volume, cost, margin) for category, (volume, cost) in sorted(grouped.items(), key=lambda item: category_order(item[0]))]
    return {'period': str(period), 'lines': lines, **statement(lines)}


def year_lines(months):
    """Year totals per category; the rate is the year's average so that messages x rate matches the amount."""
    grouped = {}
    for line in (line for month in months for line in month['lines']):
        totals = grouped.setdefault(line['category'], [0, 0.0])
        totals[0] += line['messages']
        totals[1] += line['amount']
    return [{'category': category, 'messages': volume, 'amount': round(amount, 2),
             'rate': round(amount / volume, 4) if volume else 0.0}
            for category, (volume, amount) in sorted(grouped.items(), key=lambda item: category_order(item[0]))]


def summarise(year, rows, margin):
    """Twelve monthly bills and the year bill, with billed figures only."""
    by_month = {month: [] for month in range(1, 13)}
    for row in rows:
        by_month[frappe.utils.getdate(row.period).month].append(row)
    months = [month_bill(date(year, month, 1), month_rows, margin) for month, month_rows in by_month.items()]
    lines = year_lines(months)
    return months, {'lines': lines, **statement(lines)}


def internal_figures(rows, months, margin):
    """System Manager only: Meta cost and the service charge earned per month and for the year."""
    cost = {month: 0.0 for month in range(1, 13)}
    for row in rows:
        cost[frappe.utils.getdate(row.period).month] += row.meta_cost or 0
    per_month = [{'period': month['period'], 'meta_cost': round(cost[index + 1], 4),
                  'margin_amount': round(month['amount'] - cost[index + 1], 4)} for index, month in enumerate(months)]
    meta_cost = sum(cost.values())
    return {'margin_percent': margin, 'meta_cost': round(meta_cost, 4),
            'margin_amount': round(sum(month['amount'] for month in months) - meta_cost, 4), 'months': per_month}


def account_channels(account):
    """WhatsApp channels of the account that the caller may read; none means no access."""
    if not isinstance(account, str) or not 1 <= len(account) <= 100:
        frappe.throw('Account is required')
    channels = frappe.get_list('Relay Channel', filters={'channel': 'WhatsApp', 'account': account}, pluck='name')
    if not channels:
        frappe.throw('WhatsApp account is not accessible', frappe.PermissionError)
    return channels


def template_counts(channels, year):
    """Outgoing WhatsApp template messages per template and site-timezone month. Imported history is not new spend."""
    window = {'channels': tuple(channels), 'sent': SENT, 'start': datetime(year, 1, 1), 'end': datetime(year + 1, 1, 1)}
    return frappe.db.sql(
        "SELECT template, month, COUNT(*) FROM (SELECT JSON_UNQUOTE(JSON_EXTRACT(message_data, '$.template.name')) "
        "template, MONTH(sent_at) month FROM `tabRelay Message` WHERE channel IN %(channels)s AND direction='Outgoing' "
        "AND legacy_source IS NULL AND status IN %(sent)s AND sent_at >= %(start)s AND sent_at < %(end)s) sends WHERE template IS NOT NULL "
        "GROUP BY template, month", window)


def template_categories(account, names):
    if not names:
        return {}
    rows = frappe.get_all('Relay WhatsApp Template', filters={'account': account, 'template_name': ['in', list(names)]},
                          fields=['template_name', 'category'])
    return {row.template_name: row.category for row in rows}


def billing_rows(account, year):
    return frappe.get_all(DOCTYPE, filters={'account': account, 'period': ['between', [date(year, 1, 1), date(year, 12, 31)]]},
                          fields=['period', 'category', 'pricing_type', 'volume', 'meta_cost', 'currency', 'fetched_at',
                                  'relay_channel', 'unsplit'],
                          order_by='period asc, category asc, pricing_type asc', limit_page_length=0)


@frappe.whitelist(methods=['GET'])
def get_billing(account, year):
    """The WhatsApp bill: messages, charge per message and amount per month and category, and template counts.
    Meta cost and the service charge go only to System Managers, under 'internal'."""
    require_access('Relay WhatsApp Billing Month')
    year, channels = valid_year(year), account_channels(account)
    margin, all_rows = margin_percent(), billing_rows(account, year)
    rows = [row for row in all_rows if not row.unsplit]
    months, total = summarise(year, rows, margin)
    template_rows = template_counts(channels, year)
    category_of = template_categories(account, {row[0] for row in template_rows})
    templates = [{'template': name, 'category': category_of.get(name) or '', 'period': str(date(year, month, 1)),
                  'messages': count} for name, month, count in template_rows]
    result = {'account': account, 'year': year, 'currency': next((row.currency for row in rows if row.currency), ''),
              'fetched_at': str(max(row.fetched_at for row in rows)) if rows else None,
              'months': months, 'total': total, 'numbers': number_bills(channels, year, rows, margin),
              'templates': templates}
    if can_configure():
        unsplit = [row for row in all_rows if row.unsplit]
        unsplit_months, unsplit_total = summarise(year, unsplit, margin)
        result['internal'] = dict(internal_figures(rows, months, margin), unsplit={
            'months': unsplit_months, 'total': unsplit_total, 'meta_cost': round(sum(row.meta_cost or 0 for row in unsplit), 4)})
    return result


def number_bills(channels, year, rows, margin):
    """One bill per WhatsApp number (Relay Account) with rows; the site bill is their total."""
    bills = []
    for channel in frappe.get_all('Relay Channel', filters={'name': ['in', channels]}, fields=CHANNEL_FIELDS,
                                  order_by='creation asc'):
        own = [row for row in rows if row.relay_channel == channel.name]
        if own:
            months, total = summarise(year, own, margin)
            bills.append({'channel': channel.name, 'label': channel.label or channel.name, 'address': channel.address or '',
                          'waba_id': channel.waba_id or '', 'months': months, 'total': total})
    return bills


@frappe.whitelist(methods=['POST'])
def refresh_billing(account, year):
    """Manager-triggered Meta read for one account and year."""
    from relay_core.whatsapp import failure_message
    require_access('Relay WhatsApp Billing Month')
    account_channels(account)
    try:
        return refresh(account, year)
    except (HubError, ValueError) as error:
        frappe.throw(failure_message(error))
