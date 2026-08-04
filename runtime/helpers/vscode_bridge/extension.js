const http = require("http");
const vscode = require("vscode");

let server;

function reply(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
  });
  response.end(body);
}

function readJson(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > 1024 * 1024) {
        reject(new Error("request too large"));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}"));
      } catch (error) {
        reject(error);
      }
    });
    request.on("error", reject);
  });
}

async function handleApply(payload) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    throw new Error("VS Code has no active text editor");
  }
  const text = String(payload.text || "");
  if (!text) {
    throw new Error("replacement text is empty");
  }
  const beforeVersion = editor.document.version;
  const selection = editor.selection;
  const start = selection.start;
  const applied = await editor.edit(
    (builder) => builder.replace(selection, text),
    { undoStopBefore: true, undoStopAfter: true }
  );
  if (!applied) {
    throw new Error("VS Code rejected the edit");
  }
  const eol = editor.document.eol === vscode.EndOfLine.CRLF ? "\r\n" : "\n";
  const normalizedText = text.replace(/\r\n|\r|\n/g, eol);
  const end = editor.document.positionAt(editor.document.offsetAt(start) + normalizedText.length);
  const verified = editor.document.getText(new vscode.Range(start, end)) === normalizedText;
  if (!verified) {
    throw new Error("VS Code did not verify the applied edit");
  }
  return {
    ok: true,
    transport: "vscode-extension-api",
    documentUri: editor.document.uri.toString(),
    documentVersionBefore: beforeVersion,
    documentVersionAfter: editor.document.version,
    isUntitled: editor.document.isUntitled,
    languageId: editor.document.languageId,
    selection: {
      start: { line: selection.start.line, character: selection.start.character },
      end: { line: selection.end.line, character: selection.end.character },
    },
    textVerified: true,
  };
}

function activate(context) {
  const port = Number.parseInt(process.env.WISP_VSCODE_BRIDGE_PORT || "", 10);
  const token = process.env.WISP_VSCODE_BRIDGE_TOKEN || "";
  if (!Number.isInteger(port) || port < 1 || port > 65535 || token.length < 16) {
    return;
  }
  server = http.createServer(async (request, response) => {
    if (request.socket.remoteAddress !== "127.0.0.1" && request.socket.remoteAddress !== "::1") {
      reply(response, 403, { ok: false, error: "local requests only" });
      return;
    }
    if (request.headers.authorization !== `Bearer ${token}`) {
      reply(response, 401, { ok: false, error: "unauthorized" });
      return;
    }
    if (request.method === "GET" && request.url === "/health") {
      reply(response, 200, { ok: true, transport: "vscode-extension-api" });
      return;
    }
    if (request.method !== "POST" || request.url !== "/apply") {
      reply(response, 404, { ok: false, error: "not found" });
      return;
    }
    try {
      reply(response, 200, await handleApply(await readJson(request)));
    } catch (error) {
      reply(response, 409, { ok: false, error: `${error.name}: ${error.message}` });
    }
  });
  server.listen(port, "127.0.0.1");
  context.subscriptions.push({ dispose: () => server?.close() });
}

function deactivate() {
  server?.close();
  server = undefined;
}

module.exports = { activate, deactivate };
