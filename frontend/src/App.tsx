import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import { AppShell, type Screen } from "./components/AppShell";
import { AddScreen } from "./screens/AddScreen";
import { QueueScreen } from "./screens/QueueScreen";
import { SearchScreen } from "./screens/SearchScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { TagsScreen } from "./screens/TagsScreen";
import { ViewerScreen } from "./screens/ViewerScreen";
import type { LibraryStats, RuntimeStatus, SearchHit } from "./types";

export default function App() {
  const [screen, setScreen] = useState<Screen>("search");
  const [stats, setStats] = useState<LibraryStats | null>(null);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [viewing, setViewing] = useState<SearchHit | null>(null);

  const refresh = useCallback(() => {
    api.stats().then(setStats).catch(() => undefined);
    api.runtime().then(setRuntime).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    // Статус-рядок показує прогрес фонової обробки. Опитування, а не потік
    // подій: запит дешевий, а WebSocket тут ускладнив би і бек, і збірку.
    const timer = window.setInterval(refresh, 2000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  if (viewing) {
    return (
      <ViewerScreen
        hit={viewing}
        onBack={() => setViewing(null)}
        onDeleted={() => {
          setViewing(null);
          refresh();
        }}
      />
    );
  }

  return (
    <AppShell screen={screen} onScreen={setScreen} stats={stats} runtime={runtime}>
      {screen === "search" && (
        <SearchScreen
          libraryEmpty={stats !== null && stats.item_count === 0}
          onOpen={setViewing}
        />
      )}
      {screen === "add" && <AddScreen onAdded={refresh} />}
      {screen === "queue" && <QueueScreen />}
      {screen === "tags" && <TagsScreen />}
      {screen === "settings" && <SettingsScreen stats={stats} runtime={runtime} />}
    </AppShell>
  );
}
