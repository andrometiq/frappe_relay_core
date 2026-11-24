// Uploads are private unless the caller needs a public file, such as a profile photo; a photo is attached to its record field.
export async function uploadFile(file, failure, { isPrivate = true, doctype, docname, fieldname } = {}) {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("is_private", isPrivate ? "1" : "0");
  for (const [key, value] of Object.entries({ doctype, docname, fieldname })) if (value) form.append(key, value);
  const response = await fetch("/api/method/upload_file", { method: "POST", credentials: "same-origin", body: form,
    headers: { "X-Frappe-CSRF-Token": window.frappe?.csrf_token || window.csrf_token || "" } });
  const body = await response.json().catch(() => null);
  if (!response.ok || !body?.message?.file_url) throw Error(failure);
  return body.message.file_url;
}

