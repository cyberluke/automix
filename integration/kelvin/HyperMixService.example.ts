/**
 * HyperMixService (EXAMPLE) — host-side service for the Kelvin / Zoo Code
 * extension. Spawns the sidecar, exposes pack assets, relays versioned
 * webview messages. Adapt namespaces to Kelvin's DI container.
 */
import * as vscode from "vscode";
import { ChildProcess, spawn } from "child_process";
import * as path from "path";
import * as readline from "readline";

const PROTOCOL = "hypermix.webview.v1";

export class HyperMixService implements vscode.Disposable {
  private sidecar: ChildProcess | null = null;
  private rl: readline.Interface | null = null;
  private pending = new Map<string | number, (v: unknown) => void>();

  constructor(private context: vscode.ExtensionContext) {}

  private sidecarPath(): string {
    const configured = vscode.workspace
      .getConfiguration("hypermix")
      .get<string>("sidecarPath");
    return (
      configured ||
      this.context.asAbsolutePath(
        path.join("bundled", "sidecar", "win32-x64", "hypermixd.exe"),
      )
    );
  }

  /** Spawn the sidecar and read NDJSON JSON-RPC responses. */
  async start(workspaceRoot: string): Promise<void> {
    if (this.sidecar) return;
    this.sidecar = spawn(this.sidecarPath(), ["--root", workspaceRoot], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.rl = readline.createInterface({ input: this.sidecar.stdout! });
    this.rl.on("line", (line) => {
      try {
        const msg = JSON.parse(line);
        if (msg.id !== undefined && this.pending.has(msg.id)) {
          this.pending.get(msg.id)!(msg);
          this.pending.delete(msg.id);
        }
      } catch {
        /* protocol error already logged to stderr */
      }
    });
    this.sidecar.stderr!.on("data", (d) => console.warn("[hypermixd]", d.toString()));
  }

  /** Call a sidecar method over the NDJSON protocol. */
  call<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    return new Promise((resolve, reject) => {
      if (!this.sidecar) return reject(new Error("sidecar not started"));
      const id = Date.now() + Math.random();
      this.pending.set(id, (msg: any) =>
        msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result as T),
      );
      this.sidecar.stdin!.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
    });
  }

  /** Webview view provider: serves the mix UI + pack assets. */
  registerView(): vscode.Disposable {
    return vscode.window.registerWebviewViewProvider("hypermix.mixView", {
      resolveWebviewView: (view) => {
        view.webview.options = { enableScripts: true };
        view.webview.html = this.renderHtml(view.webview);
        view.webview.onDidReceiveMessage((msg) => {
          if (msg?.protocol !== PROTOCOL) return; // reject foreign versions
          this.handleWebviewCommand(view.webview, msg);
        });
      },
    });
  }

  private async handleWebviewCommand(webview: vscode.Webview, msg: any): Promise<void> {
    switch (msg.type) {
      case "pack.load": {
        const result = await this.call("pack.inspect", { packDir: msg.payload.rootUrl });
        webview.postMessage({ protocol: PROTOCOL, id: msg.id, type: "pack.loaded", payload: result });
        break;
      }
      case "player.play":
      case "player.next":
      case "player.hotSwap":
        // Player runs in the webview; the host only supplies assets + compiler.
        break;
    }
  }

  private renderHtml(webview: vscode.Webview): string {
    const script = webview.asWebviewUri(
      vscode.Uri.file(this.context.asAbsolutePath("bundled/player/webview.js")),
    );
    return `<!doctype html><html><body>
      <div id="hypermix-root"></div>
      <script src="${script}"></script>
    </body></html>`;
  }

  dispose(): void {
    this.sidecar?.kill();
    this.rl?.close();
  }
}
