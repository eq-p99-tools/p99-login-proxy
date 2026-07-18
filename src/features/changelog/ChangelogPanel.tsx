import { useEffect, useState } from "react";

import { ErrorAlert, GroupBox } from "../../components";
import { useDesktopClient } from "../../app/AppProviders";

export function ChangelogPanel() {
  const client = useDesktopClient();
  const [html, setHtml] = useState<string>("Loading…");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void client
      .fetchGithubChangelog()
      .then(setHtml)
      .catch(async () => {
        try {
          setHtml(await client.getChangelog());
        } catch (e) {
          setError(String(e));
        }
      });
  }, [client]);

  return (
    <section className="panel changelog-panel">
      <GroupBox title="Version History">
        <div
          className="changelog-view"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </GroupBox>
      {error ? <ErrorAlert message={error} /> : null}
    </section>
  );
}
