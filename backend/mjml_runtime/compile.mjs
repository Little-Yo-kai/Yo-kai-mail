import mjml2html from "mjml";

let source = "";

for await (const chunk of process.stdin) {
  source += chunk;
}

if (!source.trim()) {
  process.stderr.write("MJML input is empty.\n");
  process.exit(2);
}

try {
  const result = await mjml2html(source, {
    validationLevel: "strict",
    beautify: false,
    keepComments: false,
  });

  process.stdout.write(
    JSON.stringify({
      html: result.html,
      errors: result.errors ?? [],
    }),
  );
} catch (error) {
  process.stderr.write(
    error instanceof Error ? error.message : String(error),
  );
  process.exit(1);
}
