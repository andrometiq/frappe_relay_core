"""Fixed fake people for the AI harness: obviously fake names, sequential fake phones, spread languages and styles."""
from dataclasses import dataclass
from functools import cache

LANGUAGES = ('English', 'Malayalam', 'Hindi', 'Tamil', 'Manglish', 'Tanglish')
LANGUAGE_CODES = {'English': 'en', 'Malayalam': 'ml', 'Hindi': 'hi', 'Tamil': 'ta', 'Manglish': 'mg', 'Tanglish': 'tg'}
# Romanised Malayalam and Tamil are Latin script; Core detects and answers them as English.
SCRIPTS = {'English': 'English', 'Malayalam': 'Malayalam', 'Hindi': 'Hindi', 'Tamil': 'Tamil',
           'Manglish': 'English', 'Tanglish': 'English'}
STYLES = ('polite', 'terse', 'angry', 'confused')
FIRST_PHONE = 917000000000  # +91 70000 00000
MEMBERS = 'members'
SALES_PARTNERS = 'sales_partners'

GROUPS = {
    'doctors': ('Meenakshi Sample', 'Anjali Example', 'Aarav Demo'),
    'employees': ('Rahul Sample', 'Pooja Example', 'Alex Demo'),
    'construction_workers': ('Murugan Sample', 'Biju Example', 'Ramesh Demo'),
    'engineers': ('Neha Sample', 'Vishnu Example', 'Senthil Demo'),
    'bus_drivers': ('Lakshmi Sample', 'Shaji Example', 'Vikas Demo'),
    'school_students': ('Harini Sample', 'Arjun Example', 'Ritu Demo'),
    'college_students': ('Nithya Sample', 'Jithin Example', 'Rohit Demo'),
    SALES_PARTNERS: ('Arumugam Sample', 'Sajeev Example', 'Deepak Demo'),
    MEMBERS: ('Divya Sample', 'Reshma Example', 'Rakesh Demo'),
}
# Each sales partner trades as its own Customer; everyone else is a Customer under their own name.
SHOPS = {'arumugam': 'Acme Sample Textiles', 'sajeev': 'Acme Sample Hosiery', 'deepak': 'Acme Sample Garments'}


@dataclass(frozen=True)
class Persona:
    group: str
    key: str
    full_name: str
    phone: str
    language: str
    style: str

    @property
    def ref(self) -> str:
        return f'{self.group}/{self.key}'

    @property
    def display_phone(self) -> str:
        return f'+{self.phone[:2]} {self.phone[2:7]} {self.phone[7:]}'

    @property
    def email(self) -> str:
        return self.full_name.casefold().replace(' ', '.') + '@example.invalid'

    @property
    def business_doctype(self) -> str:
        return 'Members' if self.group == MEMBERS else 'Customer'

    @property
    def customer_name(self) -> str:
        return SHOPS.get(self.key, self.full_name)

    @property
    def script(self) -> str:
        return SCRIPTS[self.language]


@cache
def personas() -> tuple[Persona, ...]:
    people = []
    for group, names in GROUPS.items():
        for name in names:
            index = len(people)
            people.append(Persona(group=group, key=name.split()[0].casefold(), full_name=name,
                                  phone=str(FIRST_PHONE + index), language=LANGUAGES[index % len(LANGUAGES)],
                                  style=STYLES[index % len(STYLES)]))
    return tuple(people)


def get(ref: str) -> Persona:
    """The persona for `group/key`; raises KeyError for an unknown reference."""
    for person in personas():
        if person.ref == ref:
            return person
    raise KeyError(f'Unknown persona {ref}')


def by_group(group: str) -> list[Persona]:
    return [person for person in personas() if person.group == group]
