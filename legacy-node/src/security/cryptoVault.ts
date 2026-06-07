import { createCipheriv, createDecipheriv, randomBytes } from "crypto";
import { env } from "../config/env";

const ALGO = "aes-256-gcm";
const IV_LENGTH = 12;

function getMasterKey(): Buffer {
  const key = Buffer.from(env.VAULT_MASTER_KEY_BASE64, "base64");
  if (key.length !== 32) {
    throw new Error("VAULT_MASTER_KEY_BASE64 must decode to 32 bytes");
  }
  return key;
}

export interface EncryptedSecret {
  iv: string;
  authTag: string;
  ciphertext: string;
}

export function encryptSecret(plainText: string): EncryptedSecret {
  const iv = randomBytes(IV_LENGTH);
  const key = getMasterKey();
  const cipher = createCipheriv(ALGO, key, iv);

  const ciphertext = Buffer.concat([cipher.update(plainText, "utf8"), cipher.final()]);
  const authTag = cipher.getAuthTag();

  return {
    iv: iv.toString("base64"),
    authTag: authTag.toString("base64"),
    ciphertext: ciphertext.toString("base64")
  };
}

export function decryptSecret(encrypted: EncryptedSecret): string {
  const key = getMasterKey();
  const iv = Buffer.from(encrypted.iv, "base64");
  const authTag = Buffer.from(encrypted.authTag, "base64");
  const ciphertext = Buffer.from(encrypted.ciphertext, "base64");

  const decipher = createDecipheriv(ALGO, key, iv);
  decipher.setAuthTag(authTag);

  const plain = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  return plain.toString("utf8");
}
