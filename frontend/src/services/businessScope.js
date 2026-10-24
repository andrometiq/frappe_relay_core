// Keep both halves of the active business together when creating conversation records.
export function businessScope({ businessDoctype, businessName }) {
  return businessDoctype && businessName
    ? { business_doctype: businessDoctype, business_name: businessName }
    : {}
}
