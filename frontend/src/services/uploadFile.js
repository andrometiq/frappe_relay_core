export async function uploadFile(file, failure) {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("is_private", "1");
  const response = await fetch("/api/method/upload_file", { method: "POST", credentials: "same-origin", body: form,
    headers: { "X-Frappe-CSRF-Token": window.frappe?.csrf_token || window.csrf_token || "" } });
  const body = await response.json().catch(() => null);
  if (!response.ok || !body?.message?.file_url) throw Error(failure);
  return body.message.file_url;
}

