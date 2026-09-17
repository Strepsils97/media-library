import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import { AppShell, type Screen } from "./components/AppShell";
import { AddScreen } from "./screens/AddScreen";
import { QueueScreen } from "./screens/QueueScreen";
import { SearchScreen } from "./screens/SearchScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { TagsScreen } from "./screens/TagsScreen";
import { ViewerScreen } from "./screens/ViewerScreen";
import type { LibraryStats, RuntimeStatus, SearchHit, UserSettings } from "./types";

export default function App() {
  const [screen, setScreen] = useState<Screen>("search");
  const [stats, setStats] = useState<LibraryStats | null>(null);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  // Перегляд гортає результати, тож йому потрібен увесь список, а не лише
  // обраний запис.
  const [viewing, setViewing] = useState<{
    hits: SearchHit[];
    index: number;
    query: string;
  } | null>(
    null,
  );
  const [settings, setSettings] = useState<UserSettings | null>(null);

  const refresh = useCallback(() => {
    api.stats().then(setStats).catch(() => undefined);
    api.runtime().then(setRuntime).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    // Статус-рядок показує прогрес фонової обробки. Опитування, а не потік
    // подій: запит дешевий, а WebSocket тут ускладнив би і бек, і збірку.
    const jobs = window.setInterval(
      () => api.runtime().then(setRuntime).catch(() => undefined),
      2000,
    );
    // А от розміри бібліотеки в секундному масштабі не змінюються, і
    // питати їх так само часто сенсу немає: у рядку стану вони служать
    // орієнтиром, а не лічильником.
    const sizes = window.setInterval(
      () => api.stats().then(setStats).catch(() => undefined),
      30000,
    );
    return () => {
      window.clearInterval(jobs);
      window.clearInterval(sizes);
    };
  }, [refresh]);

  useEffect(() => {
    api.settings().then(setSettings).catch(() => undefined);
  }, []);

  useEffect(() => {
    // Тема живе на кореневому елементі: CSS-змінні перевизначаються за
    // [data-theme], тож перемикання не потребує перерендеру дерева.
    document.documentElement.dataset.theme = settings?.theme ?? "dark";
  }, [settings?.theme]);

  if (viewing) {
    return (
      <ViewerScreen
        hits={viewing.hits}
        index={viewing.index}
        query={viewing.query}
        onIndex={(index) => setViewing({ ...viewing, index })}
        onBack={() => setViewing(null)}
        onChanged={refresh}
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
          onOpen={(hits, index, query) => setViewing({ hits, index, query })}
        />
      )}
      {screen === "add" && <AddScreen onAdded={refresh} />}
      {screen === "queue" && <QueueScreen />}
      {screen === "tags" && <TagsScreen />}
      {screen === "settings" && (
        <SettingsScreen stats={stats} runtime={runtime} onSettings={setSettings} />
      )}
    </AppShell>
  );
}
