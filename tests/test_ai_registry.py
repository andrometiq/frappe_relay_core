"""Tool registry: schemas from hints, hook loading, approval by code hash, audience and scoped tool reads."""
import enum
import json
import sys
import types
import unittest
from contextlib import contextmanager
from typing import Annotated, Literal, Optional, TypedDict
from unittest.mock import Mock, patch

from test_ai_capabilities import CapabilityCase
from test_ai_skills import Doc, framework, module
from relay_core.ai.registry import ToolContext, relay_tool
from relay_core.ai.registry import tool as registry_tool
from relay_core.ai.registry.schema import build_schema
from relay_core.ai.tools import check_customer_doctype


class Size(enum.Enum):
    SMALL = 'S'
    LARGE = 'L'


class Address(TypedDict):
    city: str
    pin: Annotated[int, 'Postal code']


@relay_tool(audience='customer', label='Open orders', business_doctype='Customer')
def open_orders(status: Annotated[Literal['Open', 'Delivered'], 'Order status'] = 'Open', limit: int = 5,
                *, ctx: ToolContext) -> dict:
    """List the sender's own open orders."""
    return {'status': status, 'limit': limit, 'business': ctx.business}


@relay_tool(audience='customer', label='Open orders', business_doctype='Customer', name='open_orders')
def open_orders_changed(status: Annotated[Literal['Open', 'Delivered'], 'Order status'] = 'Open', limit: int = 5,
                        *, ctx: ToolContext) -> dict:
    """List the sender's own open orders."""
    return {'status': status, 'limit': limit + 1}


@relay_tool(audience='staff', label='Margins')
def margins(*, ctx: ToolContext) -> dict:
    """Staff margin summary."""
    return {}


class SchemaTests(unittest.TestCase):
    def test_hints_give_a_closed_schema(self):
        def sample(name: Annotated[str, 'Customer name'], size: Size, tags: list[str], address: Address,
                   note: Optional[str] = None, count: Annotated[int | None, 'How many'] = None,
                   ratio: float = 1.0, urgent: bool = False, *, ctx): ...
        schema = build_schema(sample)
        self.assertEqual(schema['required'], ['name', 'size', 'tags', 'address'])
        self.assertFalse(schema['additionalProperties'])
        properties = schema['properties']
        self.assertEqual(properties['name'], {'type': 'string', 'description': 'Customer name'})
        self.assertEqual(properties['size'], {'type': 'string', 'enum': ['S', 'L']})
        self.assertEqual(properties['tags'], {'type': 'array', 'items': {'type': 'string'}})
        self.assertEqual(properties['address'], {'type': 'object', 'additionalProperties': False, 'required': ['city', 'pin'],
            'properties': {'city': {'type': 'string'}, 'pin': {'type': 'integer', 'description': 'Postal code'}}})
        self.assertEqual(properties['note'], {'type': 'string'})
        self.assertEqual(properties['count'], {'type': 'integer', 'description': 'How many'})
        self.assertEqual((properties['ratio'], properties['urgent']), ({'type': 'number'}, {'type': 'boolean'}))
        self.assertNotIn('ctx', properties)

    def test_open_or_untyped_parameters_are_refused(self):
        def untyped(value, *, ctx): ...
        def mapping(value: dict, *, ctx): ...
        def bare_list(value: list, *, ctx): ...
        def union(value: int | str, *, ctx): ...
        def mixed(value: Literal['a', 1], *, ctx): ...
        def spread(*values: int, ctx): ...
        for function in (untyped, mapping, bare_list, union, mixed, spread):
            with self.subTest(function=function.__name__), self.assertRaises(TypeError):
                build_schema(function)

    def test_decorator_needs_keyword_context_docstring_audience_and_kind(self):
        def positional(ctx): """Doc."""
        def undocumented(*, ctx): ...
        with self.assertRaises(TypeError):
            relay_tool(audience='customer', label='Tool')(positional)
        with self.assertRaises(ValueError):
            relay_tool(audience='customer', label='Tool')(undocumented)
        for options in ({'audience': 'public', 'label': 'Tool'}, {'audience': 'customer', 'label': 'Tool', 'kind': 'write'},
                        {'audience': 'customer', 'label': ''}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                relay_tool(**options)

    def test_arguments_are_validated_against_the_schema(self):
        ctx = ToolContext(run=None, skill=None, user='sam@example.com', business=('Customer', 'Acme Textiles'), scope={})
        self.assertEqual(open_orders({'status': 'Delivered'}, ctx),
                         {'status': 'Delivered', 'limit': 5, 'business': ('Customer', 'Acme Textiles')})
        for arguments in ({'status': 'Cancelled'}, {'limit': '5'}, {'customer': 'Kestrel Traders'}, {'ctx': None}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                open_orders(arguments, ctx)

    def test_built_in_stubs_fix_their_contracts(self):
        from relay_core.ai.fact_memory import memory_block, remember
        from relay_core.ai.knowledge_base.retriever import search_knowledge
        from relay_core.ai.playbooks import load_playbook
        self.assertEqual(search_knowledge.parameters['required'], ['query'])
        self.assertEqual(load_playbook.parameters['required'], ['name'])
        self.assertEqual(remember.parameters['required'], ['content'])
        self.assertEqual(remember.parameters['properties']['memory_id']['type'], 'string')
        self.assertEqual({tool.audience for tool in (search_knowledge, load_playbook, remember)}, {'customer'})
        ctx = ToolContext(run=None, skill=None, user='sam@example.com', business=('Customer', 'Acme Textiles'), scope={})
        with self.assertRaisesRegex(ValueError, '^Knowledge search is unavailable$'):
            search_knowledge({'query': 'event pass'}, ctx)
        self.assertEqual(memory_block(None, ('Customer', ''), 'delivery'), [])


class ToolSyncTests(CapabilityCase):
    def setUp(self):
        super().setUp()
        self.rows = {}
        def insert(doc, **kw):
            self.rows[doc.capability_key] = doc
            return doc
        self.enterContext(patch.object(Doc, 'insert', insert))
        self.f.new_doc = lambda doctype: Doc(doctype=doctype, flags=Doc())
        self.f.db.exists.side_effect = lambda doctype, name: doctype == 'DocType' or name in self.rows
        self.f.get_doc.side_effect = lambda doctype, name: self.rows[name]
        self.f.get_all.side_effect = lambda doctype, filters, pluck: [name for name in self.rows
            if name not in filters['name'][1] and self.rows[name].status != 'Missing']
        self.f.db.set_value.side_effect = lambda doctype, name, field, value: self.rows[name].update({field: value})
        self.enterContext(patch.dict(sys.modules, {'frappe.utils': types.SimpleNamespace(now_datetime=lambda: 'now')}))
        self.hooks['acme_app'] = {'relay_ai_tools': ['acme_app.relay.tools.open_orders'], 'relay_ai_capability_prefix': ['acme']}
        self.declared['acme_app.relay.tools.open_orders'] = open_orders

    def test_tool_rows_wait_for_approval_and_a_code_change_marks_changed(self):
        self.capabilities.sync()
        row = self.rows['acme.open_orders']
        manifest = json.loads(row.manifest)
        self.assertEqual((row.kind, row.status, row.app), ('Tool', 'Pending approval', 'acme_app'))
        self.assertEqual((manifest['audience'], manifest['tool_kind'], manifest['path']),
                         ('customer', 'read', 'acme_app.relay.tools.open_orders'))
        self.assertEqual(manifest['code_hash'], open_orders.code_hash)
        self.capabilities.mark_approved(row, 'manager')
        self.capabilities.sync()
        self.assertEqual(row.status, 'Approved')
        self.declared['acme_app.relay.tools.open_orders'] = open_orders_changed
        self.capabilities.sync()
        self.assertEqual(row.status, 'Changed')
        self.assertNotEqual(open_orders.code_hash, open_orders_changed.code_hash)

    def test_hook_path_must_belong_to_the_app(self):
        self.hooks['acme_app']['relay_ai_tools'] = ['relay_core.ai.playbooks.load_playbook']
        with self.assertRaisesRegex(ValueError, 'own module'):
            self.capabilities.sync()

    def test_import_error_skips_the_tool_and_marks_it_missing(self):
        self.capabilities.sync()
        self.declared.pop('acme_app.relay.tools.open_orders')
        self.capabilities.sync()
        self.assertEqual(self.rows['acme.open_orders'].status, 'Missing')
        self.f.log_error.assert_called_once()

    def test_a_key_declared_as_pack_and_tool_fails_the_load(self):
        self.declare('acme_app', 'acme', {'acme.open_orders': dict(self.declared['relay_core.ai.builtin_capabilities.CAPABILITIES']['erpnext.supplier_ledger'])})
        self.hooks['acme_app']['relay_ai_tools'] = ['acme_app.relay.tools.open_orders']
        with self.assertRaisesRegex(ValueError, 'packs and as tools'):
            self.capabilities.sync()


class OfferedToolTests(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.rows = {'acme.open_orders': dict(kind='tool', audience='customer', business_doctype='Customer',
                                              path='acme_app.relay.tools.open_orders', code_hash=open_orders.code_hash),
                     'acme.margins': dict(kind='tool', audience='staff', business_doctype=None,
                                          path='acme_app.relay.tools.margins', code_hash=margins.code_hash),
                     'erpnext.customer_ledger': dict(kind='read')}
        self.approved = set(self.rows)
        def active(key):
            if key not in self.approved:
                raise ValueError('Capability is not approved')
            return self.rows[key]
        self.enterContext(patch('relay_core.ai.capabilities.active', side_effect=active))
        self.f.get_attr = lambda path: {'acme_app.relay.tools.open_orders': open_orders,
                                        'acme_app.relay.tools.margins': margins}[path]
        self.enterContext(patch.object(registry_tool, 'frappe', self.f))
        self.skill = Doc(business_doctype='Customer', allowed_tools=json.dumps(
            [{'capability': key} for key in ('erpnext.customer_ledger', 'acme.open_orders', 'acme.margins')]))
        self.ctx = ToolContext(run='RUN-1', skill=self.skill, user='sam@example.com',
                               business=('Customer', 'Acme Textiles'), scope={'company': 'Acme Textiles'})

    def test_only_approved_customer_tools_of_the_business_type_are_offered(self):
        self.assertEqual(registry_tool.offered(self.skill), [('acme.open_orders', open_orders)])
        self.assertEqual(registry_tool.offered(self.skill, 'staff'), [('acme.margins', margins)])
        self.approved.discard('acme.open_orders')
        self.assertEqual(registry_tool.offered(self.skill), [])
        self.approved.add('acme.open_orders')
        self.skill.business_doctype = 'Supplier'
        self.assertEqual(registry_tool.offered(self.skill), [])

    def test_call_rechecks_approval_audience_and_code(self):
        self.assertEqual(registry_tool.call('acme.open_orders', {}, self.ctx)['limit'], 5)
        with self.assertRaisesRegex(ValueError, 'another audience'):
            registry_tool.call('acme.margins', {}, self.ctx)
        self.rows['acme.open_orders'] = dict(self.rows['acme.open_orders'], code_hash='old')
        with self.assertRaisesRegex(ValueError, 'changed'):
            registry_tool.call('acme.open_orders', {}, self.ctx)
        self.approved.discard('acme.open_orders')
        with self.assertRaisesRegex(ValueError, 'not approved'):
            registry_tool.call('acme.open_orders', {}, self.ctx)

    def test_read_packs_skip_selected_tools(self):
        from relay_core.ai import tools
        self.rows['erpnext.customer_ledger'] = dict(kind='read', business_doctype='Customer', doctype='GL Entry')
        self.rows['acme.open_orders'] = dict(self.rows['acme.open_orders'], kind='tool')
        self.assertEqual(tools.contracts(self.skill), [self.rows['erpnext.customer_ledger']])

    def test_a_read_pack_of_staff_notes_stops_the_skill(self):
        from relay_core.ai import tools
        self.rows['erpnext.customer_ledger'] = dict(kind='read', business_doctype='Customer', doctype='Relay Internal Comment')
        with self.assertRaisesRegex(ValueError, 'staff-only'):
            tools.contracts(self.skill)


FIELDS = {'customer': Doc(fieldname='customer', fieldtype='Link', options='Customer'),
          'company': Doc(fieldname='company', fieldtype='Link', options='Company'),
          'status': Doc(fieldname='status', fieldtype='Select'), 'transaction_date': Doc(fieldname='transaction_date', fieldtype='Date'),
          'terms': Doc(fieldname='terms', fieldtype='Text')}


class ToolContextTests(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.f.get_list.return_value = [Doc(name='SO-0001')]
        self.fields = dict(FIELDS)
        self.meta = Doc(fields=list(self.fields.values()), get_field=lambda name: self.fields.get(name))
        shared = types.SimpleNamespace(get_readable_meta=lambda doctype: self.meta, is_sensitive_field=lambda name: False)
        self.scope_checks = Mock()
        self.users = []
        @contextmanager
        def as_user(user):
            self.users.append(user)
            yield
        relay_tools = types.SimpleNamespace(as_user=as_user, company_neutral=Mock(side_effect=ValueError('not neutral')),
            check_customer_doctype=check_customer_doctype,
            Reader=lambda *args: types.SimpleNamespace(check_scope=self.scope_checks))
        self.scoped = Mock(return_value=Doc(name='SO-0001', status='Open', transaction_date='2026-11-01'))
        self.identity = Mock()
        self.enterContext(patch.dict(sys.modules, {'frappe_tools.ai.tools': shared, 'relay_core.ai.tools': relay_tools,
            'relay_core.business_access': types.SimpleNamespace(scoped_document=self.scoped),
            'relay_core.ai.identity': types.SimpleNamespace(validate=self.identity)}))
        self.context = module('relay_core/ai/registry/context.py', self.f)
        self.ctx = self.context.ToolContext(run='RUN-1', skill=Doc(business_doctype='Customer'), user='sam@example.com',
                                            business=('Customer', 'Acme Textiles'), scope={'company': 'Acme Textiles'})

    def test_reads_apply_business_and_company_as_the_run_user(self):
        rows = self.ctx.read_list('Sales Order', fields=['name', 'status'], filters={'status': 'Open'}, limit=3)
        self.assertEqual(rows, [{'name': 'SO-0001', 'status': 'Open'}])
        fixed = {'customer': 'Acme Textiles', 'company': 'Acme Textiles'}
        self.assertEqual(self.f.get_list.call_args.kwargs['filters'], dict(fixed, status='Open'))
        self.assertEqual(self.f.get_list.call_args.kwargs['page_length'], 3)
        self.scoped.assert_called_once_with('Sales Order', 'SO-0001', fixed, ['name', 'status'])
        self.assertEqual((self.users, self.scope_checks.call_count), (['sam@example.com'], 2))
        self.identity.assert_called_with({}, {'company': 'Acme Textiles'}, ('Customer', 'Acme Textiles'))
        self.assertEqual(self.identity.call_count, 2)

    def test_code_tools_cannot_read_staff_notes_or_ticket_internals(self):
        for doctype in ('Relay Internal Comment', 'Comment', 'Relay Ticket', 'Relay Automation Run'):
            with self.subTest(doctype=doctype), self.assertRaisesRegex(ValueError, 'unavailable'):
                self.ctx.read_list(doctype, fields=['name'])
        self.f.get_list.assert_not_called()

    def test_reads_need_the_linked_sender_the_skill_business_type_and_a_company(self):
        def unlinked(*args):
            raise ValueError('The sender is not linked to this business record')
        self.identity.side_effect = unlinked
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            self.ctx.read_list('Sales Order', fields=['name'])
        self.identity.side_effect = None
        for business, scope in ((('Supplier', 'Kestrel Traders'), {'company': 'Acme Textiles'}),
                                (('Customer', 'Acme Textiles'), {'company': None})):
            ctx = self.context.ToolContext(run='RUN-1', skill=Doc(business_doctype='Customer'), user='sam@example.com',
                                           business=business, scope=scope)
            with self.subTest(business=business, scope=scope), self.assertRaisesRegex(ValueError, 'unavailable'):
                ctx.read_doc(business[0], business[1], fields=['name'])
        self.f.get_list.assert_not_called()

    def test_filters_only_narrow_and_unsafe_fields_or_limits_fail(self):
        for call in (lambda: self.ctx.read_list('Sales Order', fields=['name'], filters={'customer': 'Kestrel Traders'}),
                     lambda: self.ctx.read_list('Sales Order', fields=['name'], filters={'company': 'Northwind Hosiery'}),
                     lambda: self.ctx.read_list('Sales Order', fields=['terms']),
                     lambda: self.ctx.read_doc('Customer', 'Kestrel Traders', fields=['name'])):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                call()
        with self.assertRaisesRegex(ValueError, 'row limit'):
            self.ctx.read_list('Sales Order', fields=['name'], limit=21)
        self.f.get_list.assert_not_called()

    def test_ambiguous_business_link_or_no_company_needs_explicit_rules(self):
        self.fields['shipping_customer'] = Doc(fieldname='shipping_customer', fieldtype='Link', options='Customer')
        self.meta.fields.append(self.fields['shipping_customer'])
        with self.assertRaises(ValueError):
            self.ctx.read_list('Sales Order', fields=['name'])
        self.ctx.read_list('Sales Order', fields=['name'], business_field='shipping_customer')
        self.assertEqual(self.f.get_list.call_args.kwargs['filters']['shipping_customer'], 'Acme Textiles')
        del self.fields['company']
        with self.assertRaises(ValueError):
            self.ctx.read_list('Sales Order', fields=['name'], business_field='customer')


if __name__ == '__main__':
    unittest.main()
