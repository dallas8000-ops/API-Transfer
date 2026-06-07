export class ProviderApiError extends Error {
  constructor(
    public readonly provider: string,
    public readonly status: number,
    message: string
  ) {
    super(message);
    this.name = "ProviderApiError";
  }
}

export interface HttpRequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  token: string;
  body?: unknown;
  query?: Record<string, string | number | undefined>;
}

function buildUrl(baseUrl: string, path: string, query?: HttpRequestOptions["query"]): string {
  const url = new URL(path.replace(/^\//, ""), baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

/**
 * Minimal authenticated JSON client. The bearer token is only used in the
 * Authorization header and is never logged or returned to callers.
 */
export async function httpJson<T>(provider: string, baseUrl: string, options: HttpRequestOptions): Promise<T> {
  const { method = "GET", path, token, body, query } = options;

  const response = await fetch(buildUrl(baseUrl, path, query), {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "application/json"
    },
    body: body === undefined ? undefined : JSON.stringify(body)
  });

  const text = await response.text();
  const parsed = text.length > 0 ? safeJsonParse(text) : undefined;

  if (!response.ok) {
    const detail = typeof parsed === "object" && parsed !== null ? JSON.stringify(parsed) : response.statusText;
    throw new ProviderApiError(provider, response.status, `Request failed: ${detail}`);
  }

  return parsed as T;
}

function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function flattenForm(body: Record<string, unknown>, prefix = ""): Array<[string, string]> {
  const pairs: Array<[string, string]> = [];
  for (const [key, value] of Object.entries(body)) {
    const fieldName = prefix ? `${prefix}[${key}]` : key;
    if (value === undefined || value === null) {
      continue;
    }
    if (typeof value === "object" && !Array.isArray(value)) {
      pairs.push(...flattenForm(value as Record<string, unknown>, fieldName));
    } else if (Array.isArray(value)) {
      value.forEach((item, index) => {
        if (item && typeof item === "object") {
          pairs.push(...flattenForm(item as Record<string, unknown>, `${fieldName}[${index}]`));
        } else {
          pairs.push([`${fieldName}[${index}]`, stringifyScalar(item)]);
        }
      });
    } else {
      pairs.push([fieldName, stringifyScalar(value)]);
    }
  }
  return pairs;
}

function stringifyScalar(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

/**
 * Authenticated form-encoded client (used by APIs like Stripe). The bearer
 * token is only used in the Authorization header and is never logged.
 */
export async function httpForm<T>(
  provider: string,
  baseUrl: string,
  options: { method?: "POST" | "GET" | "DELETE"; path: string; token: string; form?: Record<string, unknown> }
): Promise<T> {
  const { method = "POST", path, token, form } = options;
  const params = new URLSearchParams();
  if (form) {
    for (const [key, value] of flattenForm(form)) {
      params.append(key, value);
    }
  }

  const response = await fetch(buildUrl(baseUrl, path), {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/x-www-form-urlencoded",
      Accept: "application/json"
    },
    body: method === "GET" ? undefined : params.toString()
  });

  const text = await response.text();
  const parsed = text.length > 0 ? safeJsonParse(text) : undefined;

  if (!response.ok) {
    const detail = typeof parsed === "object" && parsed !== null ? JSON.stringify(parsed) : response.statusText;
    throw new ProviderApiError(provider, response.status, `Request failed: ${detail}`);
  }

  return parsed as T;
}
