import { createApp } from "./app";
import { env } from "./config/env";
import { logger } from "./logger";

const app = createApp();

app.listen(env.PORT, () => {
  logger.info({ port: env.PORT }, "API Transfer service listening");
});
