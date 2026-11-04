"""The trusted run context a code tool receives. The model never sees it and cannot change it."""
import dataclasses
from dataclasses import dataclass
from typing import Any

import frappe

MAX_ROWS = 20


@dataclass(frozen=True, kw_only=True)
class ToolContext:
    """Run, skill and the authenticated sender scope from `service.context`; reads narrow that scope only."""
    run: str | None
    skill: Any
    user: str
    business: tuple[str, str]
    scope: dict
    language: str = ''
    deadline: float | None = None
    # Knowledge sources whose chunks the run returned; delivery checks them again.
    sources: list = dataclasses.field(default_factory=list)

    def read_list(self, doctype: str, *, fields: list[str], filters: dict | None = None, limit: int = 5,
                  order_by: str = 'name asc', business_field: str | None = None) -> list[dict]:
        """Rows of the sender's own business, read as the run user with the same rules as a read pack."""
        if type(limit) is not int or not 1 <= limit <= MAX_ROWS:
            raise ValueError('Invalid row limit')
        return self.read(doctype, fields, filters or {}, limit, order_by, business_field)

    def read_doc(self, doctype: str, name: str, *, fields: list[str], business_field: str | None = None) -> dict:
        rows = self.read(doctype, fields, {'name': name}, 1, 'name asc', business_field)
        if not rows:
            raise ValueError('No readable business data')
        return rows[0]

    def read(self, doctype, fields, filters, limit, order_by, business_field):
        from relay_core.ai.identity import validate
        from relay_core.ai.tools import Reader, as_user
        from relay_core.business_access import scoped_document
        try:
            reader = Reader(self.skill, self.user, self.business, self.scope)
            reader.check_scope()
            if self.business[0] != self.skill.business_doctype:
                raise ValueError('Tool is outside the skill')
            validate({}, self.scope, self.business)
            fixed = self.fixed_filters(doctype, fields, business_field)
            for key, value in filters.items():
                if key in fixed and value != fixed[key]:
                    raise ValueError('Filters can only narrow the sender scope')
            with as_user(self.user):
                names = frappe.get_list(doctype, filters=dict(filters, **fixed), fields=['name'],
                                        page_length=limit, order_by=order_by)
                rows = []
                for row in names:
                    doc = scoped_document(doctype, row.name, fixed, fields)
                    rows.append({field: doc.get(field) for field in fields})
            reader.check_scope()
            validate({}, self.scope, self.business)
            return rows
        except Exception:
            # Never expose permission errors containing inaccessible document names.
            raise ValueError('Business data is unavailable') from None

    def fixed_filters(self, doctype, fields, business_field):
        """The business link and company of the sender scope, under the field rules of read packs."""
        from frappe_tools.ai.tools import get_readable_meta
        from relay_core.ai.capabilities import validate_field
        from relay_core.ai.tools import check_customer_doctype, company_neutral
        check_customer_doctype(doctype)
        meta = get_readable_meta(doctype)
        for field in fields:
            validate_field(meta, {'name': field, 'model': True})
        if doctype == self.business[0]:
            fixed = {'name': self.business[1]}
        else:
            links = [field.fieldname for field in meta.fields if field.fieldtype == 'Link' and field.options == self.business[0]]
            field = business_field or (links[0] if len(links) == 1 else None)
            if field not in links:
                raise ValueError('Name the one field that links to the business')
            fixed = {field: self.business[1]}
        company = meta.get_field('company')
        if company and company.fieldtype == 'Link' and company.options == 'Company':
            if not self.scope.get('company'):
                raise ValueError('The sender scope has no company')
            fixed['company'] = self.scope['company']
        else:
            company_neutral(doctype)
        return fixed
