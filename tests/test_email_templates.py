import unittest
from relay_core.email_templates import render, render_text


class EmailTemplateTests(unittest.TestCase):
    def test_sanitized_templates_are_decoded_once_before_html_escaping(self):
        result = render('Order &quot;{qty}&quot;', 'Local &amp; team &lt;review&gt; {value}',
            {'qty': 25, 'value': 'A & B <item> "quoted" &amp; literal'},
            'Support &amp; team &lt;desk&gt; &#x27;reply&#x27;')
        self.assertEqual(result['subject'], 'Order "25"')
        self.assertEqual(result['body'], 'Local & team <review> A & B <item> "quoted" &amp; literal\n\nSupport & team <desk> \'reply\'')
        self.assertIn('Local &amp; team &lt;review&gt;', result['html'])
        self.assertIn('&amp;amp; literal', result['html'])
        self.assertNotIn('<item>', result['html'])

    def test_subject_text_html_and_signature_are_rendered_without_markup_execution(self):
        values = {'name': '<img src=x onerror=alert(1)>', 'qty': 25}
        result = render('Order {qty}', 'Order {name}\nQuantity {qty}', values, 'A & B <Support>')
        self.assertEqual(result['subject'], 'Order 25')
        self.assertIn(values['name'], result['body'])
        self.assertNotIn('<img', result['html'])
        self.assertIn('&lt;img', result['html'])
        self.assertTrue(result['html'].endswith('A &amp; B &lt;Support&gt;</div>'))
        self.assertIn('<br>', result['html'])

    def test_fields_are_declared_no_attribute_traversal_code_or_formatting(self):
        for body in ('{customer}', '{name.__class__}', '{name[0]}', '{qty!r}', '{qty:04}', '{'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                render('Order', body, {'name': 'C1', 'qty': 25})
        self.assertEqual(render_text('{{literal}} {qty}', {'qty': 25}), '{literal} 25')

    def test_header_injection_empty_and_limits(self):
        for subject in ('Order\r\nBcc: x@example.invalid', '{name}', '', 'x' * 999):
            with self.subTest(subject=subject), self.assertRaises(ValueError):
                render(subject, 'Quantity 25', {'name': 'x\nInjected'})
        with self.assertRaises(ValueError): render('Order', 'x' * 100000, {}, 'signature')
        with self.assertRaises(ValueError): render('Order', 'quantity', {}, 'x' * 2001)
        with self.assertRaises(ValueError): render_text('x' * 4097, {}, limit=4096)
