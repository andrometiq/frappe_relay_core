# Contact spreadsheets

Communication Managers and System Managers can import and export from Contacts.

Export downloads an Excel file with Mobile, Email, Contact name, Business type and Business record columns. It includes the contact's primary mobile and email, one row per readable business link. Unlinked contacts have blank business columns. Contact and linked-record read permissions apply.

Import accepts Excel (.xlsx) and UTF-8 CSV files with those five columns, up to 2000 nonempty rows and 5 MB. Supply a mobile or email. Business type and record must both be filled or both blank; the type must be enabled and the exact record name must be readable. Blank contact names use the mobile or email.

Preview shows every row as Create contact, Add link, Already linked - skip, or Error with a reason. Rows are paged in groups of 50. Mobile normalization matches bulk campaigns, including Excel numeric and scientific notation. The optional WhatsApp channel supplies the country; otherwise the system country is used. New mobile contacts are enrolled when a channel is selected. No messages are sent.

Import rechecks the file and permissions, applies valid rows and reports contacts created, links added, skips and errors. Existing mobile or email identities reuse their contact. Conflicting identities require review. Repeated identities and links within the file are merged. Existing contact names and identities are retained; only missing business links are added. Unreadable links are preserved. Reimporting the same file skips existing links.
