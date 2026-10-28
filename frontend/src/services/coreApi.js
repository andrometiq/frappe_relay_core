import { serverError } from './serverError.js';
import { invalidateReads } from './realtime.js';
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
    const message = response.status === 401
      ? "Your session has expired. Sign in again to continue."
      : serverError(body, response.status === 403
        ? "You do not have permission for this action."
        : "Action was not confirmed. Check the channel configuration and permissions before retrying.");
    throw Object.assign(Error(message), {
      status: response.status,
      exceptionType: typeof body?.exc_type === 'string' ? body.exc_type : '',
    });
  }
  return body.message;
}
export async function coreApi(method, values = {}, write = false, options = {}) {
  const result = await frappeRequest("relay_core." + method, values, write, options);
  if (write && (['message_reads.mark', 'message_reads.mark_chat', 'business_inbox.mark_visible'].includes(method) ||
    (['inbox.update', 'business_inbox.read'].includes(method) && values.last_read))) invalidateReads();
  return result;
}
