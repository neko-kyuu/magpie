import { EventEmitter } from "node:events";
import type { Readable } from "node:stream";

export class JsonlReader<T> extends EventEmitter {
  private buffer = "";

  constructor(stream: Readable) {
    super();
    stream.setEncoding("utf8");
    stream.on("data", (chunk: string) => {
      this.buffer += chunk;
      this.drain();
    });
    stream.on("error", (err) => this.emit("error", err));
    stream.on("end", () => this.emit("end"));
  }

  private drain() {
    while (true) {
      const newlineIndex = this.buffer.indexOf("\n");
      if (newlineIndex < 0) return;
      const line = this.buffer.slice(0, newlineIndex).trim();
      this.buffer = this.buffer.slice(newlineIndex + 1);
      if (!line) continue;
      try {
        const obj = JSON.parse(line) as T;
        this.emit("message", obj);
      } catch (err) {
        this.emit("parse_error", { line, err });
      }
    }
  }
}

