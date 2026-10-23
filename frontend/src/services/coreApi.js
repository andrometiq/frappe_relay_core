export async function frappeRequest(
  method,
  values = {},
  write = false,
  options = {},
) {
  const query = new URLSearchParams(
    Object.entries(values).filter(([, value]) => value != null),
  );
  let response;
  try {
    response = await fetch(
      "/api/method/" + method + (write || !query.size ? "" : "?" + query),
      {
        method: write ? "POST" : "GET",
        credentials: "same-origin",
        signal: options.signal,
        keepalive: Boolean(options.keepalive),
        headers: {
          Accept: "application/json",
          ...(write
            ? {
                "Content-Type": "application/json",
                "X-Frappe-CSRF-Token":
                  window.frappe?.csrf_token || window.csrf_token || "",
              }
            : {}),
        },
        ...(write ? { body: JSON.stringify(values) } : {}),
      },
    );
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw Error(
      "Connection lost. Your draft is preserved. Check the connection before retrying.",
    );
  }
  const body = await response.json().catch(() => null);
  if (
    !response.ok ||
    !body ||
    body.exc ||
    body.exception ||
    !("message" in body)
  ) {
    if (response.status === 401)
      throw Object.assign(Error("Your session has expired. Sign in again to continue."), {status:401});
    if (response.status === 403)
      throw Object.assign(Error("You do not have permission for this action."), {status:403});
    throw Error(
      "Action was not confirmed. Check the channel configuration and permissions before retrying.",
    );
  }
  return body.message;
}
export function coreApi(method, values = {}, write = false, options = {}) {
  return frappeRequest("relay_core." + method, values, write, options);
}
