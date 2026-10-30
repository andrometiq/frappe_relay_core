"""Bounded outgoing privacy checks; names use primary keys, never unindexed title scans."""
import json
import re
import unicodedata

import frappe

REASON = 'Reply blocked: possible private data'
EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
PHONE = re.compile(r'(?<![\w])\+?\d(?:[\d ()\-]*\d)?(?![\w])')
DATE = re.compile(r'\b(?:\d{4}-\d{2}-\d{2}|\d{2}([-/.])\d{2}\1\d{4})\b')
DOCUMENT = re.compile(r'\b[A-Za-z][A-Za-z0-9]*(?:[-_/.][A-Za-z0-9]+)+\b')
MONEY = re.compile(r'\b(?:\d+(?:,\d+)+(?:\.\d+)?|\d+\.\d+)\b')


class ReplyBlocked(ValueError):
    def __init__(self):
        super().__init__(REASON)


def phones(text):
    text = ''.join(str(unicodedata.decimal(char)) if char.isdecimal() else char for char in text)
    for pattern in (DOCUMENT, DATE, MONEY):
        text = pattern.sub('|', text)
    return {digits for match in PHONE.finditer(text)
            if 10 <= len(digits := re.sub(r'\D', '', match[0])) <= 15}


def contacts(*evidence):
    """Keep only contact values from the sender's authorized model inputs for delivery."""
    found = set()
    for value in evidence:
        if isinstance(value, dict):
            found.update(contacts(*value.values()))
        elif isinstance(value, (list, tuple)):
            found.update(contacts(*value))
        else:
            text = str(value or '')
            found.update(email.casefold() for email in EMAIL.findall(text))
            found.update(phones(text))
    return sorted(found)


def copied(reply, sources):
    def words_of(text):
        return ''.join(char if char.isalnum() or unicodedata.category(char).startswith('M') else ' '
                       for char in text.casefold()).split()
    words = words_of(reply)
    runs = {tuple(words[i:i + 12]) for i in range(len(words) - 11)}
    for source in sources:
        words = words_of(source or '')
        if any(tuple(words[i:i + 12]) in runs for i in range(len(words) - 11)):
            return True
    return False


def check(reply, skill, scope, *, evidence=(), knowledge=''):
    """Raise without including leaked text. Allow authorized evidence and Company contacts.

    Customer/Supplier checks cover exact capitalised primary-key names up to six words.
    Unindexed display names, lowercase names and other business DocTypes are not scanned.
    Numeric strings of 10–15 digits, excluding dates, document IDs and money, may be phones.
    """
    from relay_core.ai.adapter import PRIVACY_REPLY, SYSTEM_RULES
    from relay_core.ai.handoff import ACKNOWLEDGEMENT
    if not reply or reply in (PRIVACY_REPLY, ACKNOWLEDGEMENT):
        return
    if copied(reply, (SYSTEM_RULES, skill.get('instructions'), skill.get('reply_style'), knowledge)):
        raise ReplyBlocked()
    emails = {value.casefold() for value in EMAIL.findall(reply)}
    numbers = phones(reply)
    if emails or numbers:
        allowed = '\n'.join(contacts(scope.get('endpoint'), evidence))
        if scope.get('company'):
            company = frappe.get_doc('Company', scope['company'])
            allowed += '\n' + str(company.get('email') or '') + '\n' + str(company.get('phone_no') or '')
        if emails - {value.casefold() for value in EMAIL.findall(allowed)} or numbers - phones(allowed):
            raise ReplyBlocked()
    # At most 6 * the reply's word count candidates, in three indexed IN queries.
    names = set()
    for phrase in re.findall(r"\b[^\W\d_]\w*(?:[-'’][\w]+)*(?:[ \t]+[^\W\d_]\w*(?:[-'’][\w]+)*)*", reply):
        words = phrase.split()
        for start, word in enumerate(words):
            if not word[0].isupper():
                continue
            for end in range(start + 1, min(start + 6, len(words)) + 1):
                names.add(' '.join(words[start:end]))
    if not names:
        return
    own = {tuple(scope['business'])} if scope.get('business') else set()
    if scope.get('contact'):
        from relay_core.business_access import candidates
        own.update(candidates(scope['contact']))
    companies = {scope.get('company')}
    if frappe.db.exists('DocType', 'Company'):
        companies.update(frappe.get_all('Company', filters={'name': ['in', sorted(names)]}, pluck='name',
                                       limit_page_length=len(names)))
    for doctype in ('Customer', 'Supplier'):
        if not frappe.db.exists('DocType', doctype):
            continue
        found = frappe.get_all(doctype, filters={'name': ['in', sorted(names)]}, pluck='name',
                               limit_page_length=len(names))
        if any((doctype, name) not in own and name not in companies for name in found):
            raise ReplyBlocked()


def check_delivery(run, skill, message, reply):
    # Core captures these values from model inputs, never from the model's reply.
    # dispatch_reply revalidates the sender scope, event context and reads first.
    decision = json.loads(run.get('decision') or '{}')
    company = frappe.db.get_value('Relay Channel', message.channel, 'company')
    from relay_core.ai.knowledge import prompt
    knowledge = prompt((message.business_doctype, message.business_name), company)
    check(reply, skill, dict(endpoint=message.sender_endpoint, company=company,
        contact=message.relay_contact, business=[message.business_doctype, message.business_name]),
        evidence=[message.get('content') or '', decision.get('reply_contacts', [])], knowledge=knowledge)
