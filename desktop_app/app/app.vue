<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { isTauriRuntime, sidecarCall } from "~/composables/useSidecar";

type StatusLevel = "info" | "success" | "warning" | "error";

type CardSchemaOption = {
  key: string;
  label: string;
};

type VerbFormOption = {
  key: string;
  label: string;
};

type VerbTypeOption = {
  key: string;
  label: string;
};

type CollectionRow = {
  id: string;
  name: string;
};

type DeckRow = {
  id: string;
  collection_id: string;
  collection_name: string;
  name: string;
  label: string;
  card_count: number;
};

type DictionaryEntry = {
  entry_id: string;
  headword: string;
  reading: string;
  english: string;
  glosses: string[];
  pos_labels: string[];
  option_label: string;
  verb_type: string;
  is_verb: boolean;
  forms?: Record<string, { kanji?: string; kana?: string }>;
};

type GlobalCardRow = {
  id: string;
  kanji: string;
  kana: string;
  english: string;
  notes: string;
  kanji_masu: string;
  kana_masu: string;
  kanji_te: string;
  kana_te: string;
  kanji_past: string;
  kana_past: string;
  kanji_negative: string;
  kana_negative: string;
  dictionary_entry_id: string;
  dictionary_headword: string;
  dictionary_reading: string;
  dictionary_gloss: string;
  dictionary_pos: string;
  verb_type: string;
  image_files: string[];
  video_files: string[];
  tags: string[];
  media_type: string;
};

type DeckCardRow = {
  id: string;
  index: number;
  kanji: string;
  kana: string;
  english: string;
  notes: string;
  schema_key: string;
  schema_label: string;
  word_form: string;
  dictionary_entry_id: string;
  dictionary_headword: string;
  dictionary_reading: string;
  dictionary_gloss: string;
  dictionary_pos: string;
  verb_type: string;
  media_type: string;
  media_files: string[];
  tags: string[];
};

type RevisionCardRow = {
  id: string;
  front: string;
  back: string;
  notes: string;
  schema_label: string;
  word_form: string;
};

type PracticeRoundCard = {
  id: string;
  prompt: string;
  hint: string;
  expected: string;
  expected_display?: string;
  accepted_answers?: string[];
};

type PracticeSummaryRow = {
  mode: string;
  prompt: string;
  hint: string;
  expected: string;
  selected: string;
  correct: boolean;
  elapsed_seconds: number;
  delta_points: number;
};

type BootstrapPayload = {
  app_title: string;
  card_schemas: CardSchemaOption[];
  verb_forms: VerbFormOption[];
  verb_types: VerbTypeOption[];
  collections: CollectionRow[];
  decks: DeckRow[];
  dashboard: {
    collection_count: number;
    deck_count: number;
    card_count: number;
    global_card_count: number;
    rows: Array<{
      collection_name: string;
      deck_name: string;
      card_count: number;
    }>;
  };
  defaults: {
    schema_key: string;
    word_form: string;
    practice_modes: Array<{ key: string; label: string }>;
  };
};

type WordFormResponse = {
  word_kind: string;
  forms: Record<string, { word?: string; reading?: string }>;
};

const tabs = [
  { key: "overview", label: "Overview" },
  { key: "dictionary", label: "Dictionary" },
  { key: "builder", label: "Card Builder" },
  { key: "pool", label: "Global Pool" },
  { key: "review", label: "Deck Review" },
  { key: "practice", label: "Revision + Games" },
  { key: "tools", label: "Scan / Import / Export" },
];

const activeTab = ref("overview");
const busyAction = ref("");
const statusLevel = ref<StatusLevel>("info");
const statusMessage = ref("");

const appTitle = ref("Anki Card Generator");
const cardSchemas = ref<CardSchemaOption[]>([]);
const verbForms = ref<VerbFormOption[]>([]);
const verbTypes = ref<VerbTypeOption[]>([]);
const collections = ref<CollectionRow[]>([]);
const decks = ref<DeckRow[]>([]);
const dashboard = ref<BootstrapPayload["dashboard"]>({
  collection_count: 0,
  deck_count: 0,
  card_count: 0,
  global_card_count: 0,
  rows: [],
});
const practiceModeOptions = ref<Array<{ key: string; label: string }>>([]);

const contextDeckId = ref("");
const cardsScope = ref<"deck" | "global">("deck");

const createCollectionName = ref("");
const renameCollectionId = ref("");
const renameCollectionName = ref("");

const createDeckCollectionId = ref("");
const createDeckName = ref("");
const renameDeckId = ref("");
const renameDeckName = ref("");

const dictionaryQuery = ref("");
const dictionaryResults = ref<DictionaryEntry[]>([]);
const dictionarySelectedIds = ref<string[]>([]);
const dictionaryDestination = ref<"deck" | "global">("deck");
const dictionaryDeckId = ref("");
const dictionarySchemaKey = ref("kana_kanji_front_english_back");
const dictionaryWordForm = ref("dictionary");
const dictionaryTags = ref("japanese,jamdict");
const dictionaryNotes = ref("");
const dictionaryEnglishOverride = ref("");

const manualDestination = ref<"deck" | "global">("global");
const manualDeckId = ref("");
const manualSchemaKey = ref("kana_kanji_front_english_back");
const manualWordKind = ref("noun");
const manualWordForm = ref("dictionary");
const manualKanji = ref("");
const manualKana = ref("");
const manualEnglish = ref("");
const manualNotes = ref("");
const manualTags = ref("manual");
const manualDictionaryEntryId = ref("");
const manualDictionaryHeadword = ref("");
const manualDictionaryReading = ref("");
const manualDictionaryGloss = ref("");
const manualDictionaryPos = ref("");
const manualVerbType = ref("other");
const manualMediaPaths = ref<string[]>([]);
const manualForms = reactive<Record<string, { word: string; reading: string }>>({
  dictionary: { word: "", reading: "" },
  masu: { word: "", reading: "" },
  te: { word: "", reading: "" },
  past: { word: "", reading: "" },
  negative: { word: "", reading: "" },
  potential: { word: "", reading: "" },
  passive: { word: "", reading: "" },
  causative: { word: "", reading: "" },
});

const globalSourceDeckId = ref("");
const globalDestinationDeckId = ref("");
const globalDestinationSchemaKey = ref("kana_kanji_front_english_back");
const globalDestinationWordForm = ref("dictionary");
const globalImportTags = ref("global_pool");
const globalSearchText = ref("");
const globalRows = ref<GlobalCardRow[]>([]);
const globalSelectedIds = ref<string[]>([]);

const reviewDeckId = ref("");
const reviewSearchText = ref("");
const reviewRows = ref<DeckCardRow[]>([]);
const reviewSelectedIds = ref<string[]>([]);
const reviewBulkSchemaKey = ref("kana_kanji_front_english_back");
const reviewConfirmDelete = ref(false);
const reviewReplaceTarget = ref("english");
const reviewReplaceMediaType = ref("image");
const reviewReplaceMediaPaths = ref<string[]>([]);
const singleEdit = reactive({
  cardId: "",
  kanji: "",
  kana: "",
  english: "",
  notes: "",
  schemaKey: "kana_kanji_front_english_back",
});

const revisionRows = ref<RevisionCardRow[]>([]);
const revisionIndex = ref(0);
const revisionShowBack = ref(false);

const practiceMode = ref("verb_sort");
const practiceRoundActive = ref(false);
const practiceRoundCards = ref<PracticeRoundCard[]>([]);
const practiceRoundIndex = ref(0);
const practiceRoundStartedAt = ref(0);
const practiceQuestionStartedAt = ref(0);
const practiceRoundElapsedSeconds = ref(0);
const practiceScore = ref(0);
const practiceCorrectCount = ref(0);
const practiceIncorrectCount = ref(0);
const practiceStreak = ref(0);
const practiceBestStreak = ref(0);
const practiceLastSpeedBonus = ref(0);
const practiceLastResultMessage = ref("");
const practiceTeInput = ref("");
const practiceAnswers = ref<PracticeSummaryRow[]>([]);
const practiceScoring = reactive({
  base_correct_points: 10,
  incorrect_penalty_points: 2,
  bucket_labels: {
    ichidan: "Ichidan",
    godan: "Godan",
    i_adj: "I-adjective (い)",
    na_adj: "Na-adjective (な)",
  } as Record<string, string>,
});

const scanDeckId = ref("");
const scanSchemaKey = ref("kana_kanji_front_english_back");
const scanWordForm = ref("dictionary");
const scanTags = ref("image_ocr");
const scanImagePaths = ref<string[]>([]);
const scanSummary = ref("");
const scanPreviewRows = ref<
  Array<{ visible_text: string; source_text: string; dictionary_entry_id: string; kanji: string; kana: string; english: string }>
>([]);
const scanErrors = ref<string[]>([]);

const importDeckId = ref("");
const importCsvPath = ref("");
const importCsvResult = ref("");

const exportDeckId = ref("");
const exportPath = ref("");

const selectedContextDeckLabel = computed(() => {
  const selected = decks.value.find((deck) => deck.id === contextDeckId.value);
  return selected?.label ?? "No deck selected";
});

const currentRevisionCard = computed(() => {
  if (!revisionRows.value.length) {
    return null;
  }
  const safeIndex = Math.min(Math.max(revisionIndex.value, 0), revisionRows.value.length - 1);
  return revisionRows.value[safeIndex];
});

const revisionProgressLabel = computed(() => {
  if (!revisionRows.value.length) {
    return "0 / 0";
  }
  const safeIndex = Math.min(Math.max(revisionIndex.value, 0), revisionRows.value.length - 1);
  return `${safeIndex + 1} / ${revisionRows.value.length}`;
});

const revisionFaceText = computed(() => {
  if (!currentRevisionCard.value) {
    return "";
  }
  return revisionShowBack.value ? currentRevisionCard.value.back : currentRevisionCard.value.front;
});

const practiceCurrentCard = computed(() => {
  if (!practiceRoundActive.value) {
    return null;
  }
  if (practiceRoundIndex.value >= practiceRoundCards.value.length) {
    return null;
  }
  return practiceRoundCards.value[practiceRoundIndex.value] ?? null;
});

const practiceProgressLabel = computed(() => {
  const total = practiceRoundCards.value.length;
  if (!total) {
    return "0 / 0";
  }
  if (!practiceRoundActive.value) {
    return `${total} / ${total}`;
  }
  const safeIndex = Math.min(Math.max(practiceRoundIndex.value, 0), total - 1);
  return `${safeIndex + 1} / ${total}`;
});

const practiceAnswerCount = computed(() => practiceAnswers.value.length);
const practiceAccuracyPercent = computed(() => {
  const attempts = practiceCorrectCount.value + practiceIncorrectCount.value;
  if (!attempts) {
    return 0;
  }
  return Math.round((practiceCorrectCount.value / attempts) * 100);
});
const practiceAverageSeconds = computed(() => {
  if (!practiceAnswers.value.length) {
    return 0;
  }
  const total = practiceAnswers.value.reduce((sum, row) => sum + row.elapsed_seconds, 0);
  return Number((total / practiceAnswers.value.length).toFixed(2));
});

const practiceSummaryRows = computed(() => {
  return practiceAnswers.value.map((row) => {
    const expectedLabel =
      row.mode === "te_form"
        ? row.expected
        : practiceScoring.bucket_labels[row.expected] ?? row.expected;
    const selectedLabel =
      row.mode === "te_form"
        ? row.selected
        : practiceScoring.bucket_labels[row.selected] ?? row.selected;
    return {
      ...row,
      expectedLabel,
      selectedLabel,
    };
  });
});

const statusClass = computed(() => `status-${statusLevel.value}`);

const manualIsVerb = computed(() =>
  ["ichidan", "godan", "suru", "suru_noun", "kuru"].includes(manualWordKind.value),
);

const canRunTauriActions = computed(() => isTauriRuntime());

const setStatus = (level: StatusLevel, message: string) => {
  statusLevel.value = level;
  statusMessage.value = message;
};

const clearStatus = () => {
  statusLevel.value = "info";
  statusMessage.value = "";
};

const ensureValueIn = (current: string, values: string[]): string => {
  if (current && values.includes(current)) {
    return current;
  }
  return values[0] ?? "";
};

const normalizeFormsPayload = () => ({
  dictionary: { ...manualForms.dictionary },
  masu: { ...manualForms.masu },
  te: { ...manualForms.te },
  past: { ...manualForms.past },
  negative: { ...manualForms.negative },
  potential: { ...manualForms.potential },
  passive: { ...manualForms.passive },
  causative: { ...manualForms.causative },
});

const applyFormsResponse = (forms: Record<string, { word?: string; reading?: string }>) => {
  const keys = ["dictionary", "masu", "te", "past", "negative", "potential", "passive", "causative"];
  for (const key of keys) {
    manualForms[key].word = String(forms[key]?.word ?? "");
    manualForms[key].reading = String(forms[key]?.reading ?? "");
  }
};

const runBusy = async (actionLabel: string, callback: () => Promise<void>) => {
  busyAction.value = actionLabel;
  try {
    await callback();
  } catch (error) {
    setStatus("error", String(error));
  } finally {
    busyAction.value = "";
  }
};

const parseDialogSelection = (picked: string | string[] | null): string[] => {
  if (!picked) {
    return [];
  }
  if (Array.isArray(picked)) {
    return picked;
  }
  return [picked];
};

const pickPaths = async (options: {
  multiple?: boolean;
  title: string;
  filters?: Array<{ name: string; extensions: string[] }>;
}) => {
  if (!isTauriRuntime()) {
    throw new Error("Tauri runtime not detected.");
  }
  const picked = await openDialog({
    multiple: options.multiple ?? false,
    directory: false,
    title: options.title,
    filters: options.filters ?? [],
  });
  return parseDialogSelection(picked);
};

const syncDeckDefaults = () => {
  const deckIds = decks.value.map((deck) => deck.id);
  const collectionIds = collections.value.map((collection) => collection.id);

  contextDeckId.value = ensureValueIn(contextDeckId.value, deckIds);
  reviewDeckId.value = ensureValueIn(reviewDeckId.value || contextDeckId.value, deckIds);
  dictionaryDeckId.value = ensureValueIn(dictionaryDeckId.value || contextDeckId.value, deckIds);
  manualDeckId.value = ensureValueIn(manualDeckId.value || contextDeckId.value, deckIds);
  globalSourceDeckId.value = ensureValueIn(globalSourceDeckId.value || contextDeckId.value, deckIds);
  globalDestinationDeckId.value = ensureValueIn(globalDestinationDeckId.value || contextDeckId.value, deckIds);
  scanDeckId.value = ensureValueIn(scanDeckId.value || contextDeckId.value, deckIds);
  importDeckId.value = ensureValueIn(importDeckId.value || contextDeckId.value, deckIds);
  exportDeckId.value = ensureValueIn(exportDeckId.value || contextDeckId.value, deckIds);

  renameCollectionId.value = ensureValueIn(renameCollectionId.value, collectionIds);
  createDeckCollectionId.value = ensureValueIn(createDeckCollectionId.value, collectionIds);
  renameDeckId.value = ensureValueIn(renameDeckId.value, deckIds);

  if (!createDeckCollectionId.value && collections.value.length) {
    createDeckCollectionId.value = collections.value[0].id;
  }
  if (!renameCollectionId.value && collections.value.length) {
    renameCollectionId.value = collections.value[0].id;
  }
  if (!renameDeckId.value && decks.value.length) {
    renameDeckId.value = decks.value[0].id;
  }
};

const refreshBootstrap = async () => {
  const payload = await sidecarCall<BootstrapPayload>("bootstrap");
  appTitle.value = payload.app_title;
  cardSchemas.value = payload.card_schemas;
  verbForms.value = payload.verb_forms;
  verbTypes.value = payload.verb_types;
  collections.value = payload.collections;
  decks.value = payload.decks;
  dashboard.value = payload.dashboard;
  practiceModeOptions.value = payload.defaults.practice_modes;

  if (!dictionarySchemaKey.value) {
    dictionarySchemaKey.value = payload.defaults.schema_key;
  }
  if (!manualSchemaKey.value) {
    manualSchemaKey.value = payload.defaults.schema_key;
  }
  if (!globalDestinationSchemaKey.value) {
    globalDestinationSchemaKey.value = payload.defaults.schema_key;
  }
  if (!reviewBulkSchemaKey.value) {
    reviewBulkSchemaKey.value = payload.defaults.schema_key;
  }
  if (!scanSchemaKey.value) {
    scanSchemaKey.value = payload.defaults.schema_key;
  }

  syncDeckDefaults();
};

const loadGlobalCards = async () => {
  const response = await sidecarCall<{ rows: GlobalCardRow[] }>("list_global_cards", {
    search: globalSearchText.value,
  });
  globalRows.value = response.rows ?? [];
  globalSelectedIds.value = globalSelectedIds.value.filter((id) =>
    globalRows.value.some((row) => row.id === id),
  );
};

const loadReviewCards = async () => {
  if (!reviewDeckId.value) {
    reviewRows.value = [];
    reviewSelectedIds.value = [];
    return;
  }
  const response = await sidecarCall<{ rows: DeckCardRow[] }>("list_deck_cards", {
    deck_id: reviewDeckId.value,
    search: reviewSearchText.value,
  });
  reviewRows.value = response.rows ?? [];
  reviewSelectedIds.value = reviewSelectedIds.value.filter((id) =>
    reviewRows.value.some((row) => row.id === id),
  );
};

const loadRevisionCards = async () => {
  if (!contextDeckId.value) {
    revisionRows.value = [];
    revisionIndex.value = 0;
    revisionShowBack.value = false;
    return;
  }
  const response = await sidecarCall<{ rows: RevisionCardRow[] }>("get_revision_cards", {
    deck_id: contextDeckId.value,
  });
  revisionRows.value = response.rows ?? [];
  if (!revisionRows.value.length) {
    revisionIndex.value = 0;
  } else if (revisionIndex.value >= revisionRows.value.length) {
    revisionIndex.value = revisionRows.value.length - 1;
  }
};

const refreshAllData = async () => {
  await refreshBootstrap();
  await Promise.all([loadGlobalCards(), loadReviewCards(), loadRevisionCards()]);
};

const toggleId = (collection: { value: string[] }, id: string) => {
  const next = [...collection.value];
  if (next.includes(id)) {
    collection.value = next.filter((item) => item !== id);
    return;
  }
  next.push(id);
  collection.value = next;
};

const selectAllDictionary = () => {
  dictionarySelectedIds.value = dictionaryResults.value.map((entry) => entry.entry_id);
};

const clearDictionarySelection = () => {
  dictionarySelectedIds.value = [];
};

const searchDictionary = async () => {
  const query = dictionaryQuery.value.trim();
  if (!query) {
    dictionaryResults.value = [];
    dictionarySelectedIds.value = [];
    setStatus("info", "Type a word to search the dictionary.");
    return;
  }
  await runBusy("Searching dictionary", async () => {
    const response = await sidecarCall<{ results: DictionaryEntry[] }>("search_dictionary", {
      query,
      limit: 50,
    });
    dictionaryResults.value = response.results ?? [];
    dictionarySelectedIds.value = [];
    if (dictionaryResults.value.length) {
      setStatus("success", `Found ${dictionaryResults.value.length} dictionary entries.`);
    } else {
      setStatus("warning", "No dictionary entries found.");
    }
  });
};

const addSelectedDictionaryEntries = async () => {
  if (!dictionarySelectedIds.value.length) {
    setStatus("warning", "Select one or more dictionary entries first.");
    return;
  }
  if (dictionaryDestination.value === "deck" && !dictionaryDeckId.value) {
    setStatus("warning", "Select a destination deck.");
    return;
  }
  await runBusy("Adding dictionary entries", async () => {
    const response = await sidecarCall<{ added: number; skipped: number }>("add_dictionary_entries", {
      entry_ids: dictionarySelectedIds.value,
      destination: dictionaryDestination.value,
      deck_id: dictionaryDeckId.value,
      schema_key: dictionarySchemaKey.value,
      word_form: dictionaryWordForm.value,
      tags: dictionaryTags.value,
      notes: dictionaryNotes.value,
      english_override: dictionaryEnglishOverride.value,
    });
    setStatus(
      "success",
      `Added ${response.added} card(s); skipped ${response.skipped} duplicate/invalid card(s).`,
    );
    await refreshAllData();
  });
};

const quickAddDictionaryEntry = async (entryId: string, destination: "deck" | "global") => {
  await runBusy("Quick add", async () => {
    const response = await sidecarCall<{ added: number; skipped: number }>("quick_add_dictionary_entry", {
      entry_id: entryId,
      destination,
      deck_id: destination === "deck" ? dictionaryDeckId.value || contextDeckId.value : "",
      schema_key: dictionarySchemaKey.value,
      word_form: dictionaryWordForm.value,
      tags: dictionaryTags.value,
      notes: dictionaryNotes.value,
      english_override: dictionaryEnglishOverride.value,
    });
    setStatus(
      response.added > 0 ? "success" : "warning",
      response.added > 0 ? "Dictionary entry added." : "Skipped add (duplicate/invalid).",
    );
    if (response.added > 0 || response.skipped > 0) {
      await refreshAllData();
    }
  });
};

const prefillManualFromDictionary = (entry: DictionaryEntry) => {
  manualKanji.value = entry.headword ?? "";
  manualKana.value = entry.reading ?? "";
  manualEnglish.value = entry.english ?? "";
  manualDictionaryEntryId.value = entry.entry_id ?? "";
  manualDictionaryHeadword.value = entry.headword ?? "";
  manualDictionaryReading.value = entry.reading ?? "";
  manualDictionaryGloss.value = entry.english ?? "";
  manualDictionaryPos.value = (entry.pos_labels ?? []).join(", ");
  manualVerbType.value = entry.verb_type || "other";

  if (entry.verb_type && ["ichidan", "godan", "suru", "suru_noun", "kuru"].includes(entry.verb_type)) {
    manualWordKind.value = entry.verb_type;
  } else if ((entry.pos_labels || []).join(" ").toLowerCase().includes("na-adjective")) {
    manualWordKind.value = "na_adj";
  } else if ((entry.pos_labels || []).join(" ").toLowerCase().includes("adjective")) {
    manualWordKind.value = "i_adj";
  } else {
    manualWordKind.value = "noun";
  }

  const forms = entry.forms ?? {};
  applyFormsResponse({
    dictionary: { word: forms.dictionary?.kanji ?? entry.headword, reading: forms.dictionary?.kana ?? entry.reading },
    masu: { word: forms.masu?.kanji, reading: forms.masu?.kana },
    te: { word: forms.te?.kanji, reading: forms.te?.kana },
    past: { word: forms.past?.kanji, reading: forms.past?.kana },
    negative: { word: forms.negative?.kanji, reading: forms.negative?.kana },
    potential: { word: "", reading: "" },
    passive: { word: "", reading: "" },
    causative: { word: "", reading: "" },
  });

  setStatus("info", "Manual card builder prefilled from selected dictionary entry.");
};

const prefillManualFromFirstDictionarySelection = () => {
  if (!dictionarySelectedIds.value.length) {
    setStatus("warning", "Select a dictionary entry first.");
    return;
  }
  const entry = dictionaryResults.value.find((row) => row.entry_id === dictionarySelectedIds.value[0]);
  if (!entry) {
    setStatus("warning", "Selected dictionary entry is no longer available.");
    return;
  }
  prefillManualFromDictionary(entry);
};

const generateManualForms = async () => {
  if (!manualKanji.value.trim() || !manualKana.value.trim()) {
    setStatus("warning", "Enter word and reading before generating forms.");
    return;
  }
  await runBusy("Generating forms", async () => {
    const response = await sidecarCall<WordFormResponse>("build_word_forms", {
      word: manualKanji.value,
      reading: manualKana.value,
      word_kind: manualWordKind.value,
    });
    applyFormsResponse(response.forms ?? {});
    setStatus("success", "Word forms updated.");
  });
};

const pickManualMedia = async () => {
  await runBusy("Selecting media", async () => {
    manualMediaPaths.value = await pickPaths({
      multiple: true,
      title: "Select media files",
      filters: [
        { name: "Media", extensions: ["png", "jpg", "jpeg", "webp", "mp4", "webm", "mov", "mp3", "wav", "m4a", "ogg"] },
      ],
    });
  });
};

const saveManualCard = async () => {
  if (manualDestination.value === "deck" && !manualDeckId.value) {
    setStatus("warning", "Select a destination deck.");
    return;
  }
  await runBusy("Saving manual card", async () => {
    const response = await sidecarCall<{ added: boolean }>("add_manual_card", {
      destination: manualDestination.value,
      deck_id: manualDeckId.value,
      schema_key: manualSchemaKey.value,
      word_form: manualWordForm.value,
      word_kind: manualWordKind.value,
      kanji: manualKanji.value,
      kana: manualKana.value,
      english: manualEnglish.value,
      notes: manualNotes.value,
      tags: manualTags.value,
      forms: normalizeFormsPayload(),
      media_paths: manualMediaPaths.value,
      dictionary_entry_id: manualDictionaryEntryId.value,
      dictionary_headword: manualDictionaryHeadword.value,
      dictionary_reading: manualDictionaryReading.value,
      dictionary_gloss: manualDictionaryGloss.value,
      dictionary_pos: manualDictionaryPos.value,
      verb_type: manualVerbType.value,
    });
    setStatus(
      response.added ? "success" : "warning",
      response.added ? "Manual card added." : "Skipped add (duplicate or invalid).",
    );
    if (response.added) {
      manualMediaPaths.value = [];
    }
    await refreshAllData();
  });
};

const importSourceDeckToGlobalPool = async () => {
  if (!globalSourceDeckId.value) {
    setStatus("warning", "Select a source deck.");
    return;
  }
  await runBusy("Importing deck into global pool", async () => {
    const response = await sidecarCall<{ added: number; skipped: number }>("import_deck_to_global", {
      deck_id: globalSourceDeckId.value,
    });
    setStatus(
      "success",
      `Imported ${response.added} card(s); skipped ${response.skipped} duplicate/invalid card(s).`,
    );
    await refreshAllData();
  });
};

const importSelectedGlobalToDeck = async () => {
  if (!globalDestinationDeckId.value) {
    setStatus("warning", "Select a destination deck.");
    return;
  }
  if (!globalSelectedIds.value.length) {
    setStatus("warning", "Select one or more global cards.");
    return;
  }
  await runBusy("Importing global cards to deck", async () => {
    const response = await sidecarCall<{ added: number; skipped: number }>("import_global_to_deck", {
      deck_id: globalDestinationDeckId.value,
      global_card_ids: globalSelectedIds.value,
      schema_key: globalDestinationSchemaKey.value,
      word_form: globalDestinationWordForm.value,
      tags: globalImportTags.value,
    });
    setStatus("success", `Imported ${response.added} card(s); skipped ${response.skipped}.`);
    globalSelectedIds.value = [];
    await refreshAllData();
  });
};

const deleteSelectedGlobalCards = async () => {
  if (!globalSelectedIds.value.length) {
    setStatus("warning", "Select one or more global cards.");
    return;
  }
  await runBusy("Deleting global cards", async () => {
    const response = await sidecarCall<{ deleted: number }>("delete_global_cards", {
      ids: globalSelectedIds.value,
    });
    setStatus("success", `Deleted ${response.deleted} global card(s).`);
    globalSelectedIds.value = [];
    await refreshAllData();
  });
};

const selectAllReviewRows = () => {
  reviewSelectedIds.value = reviewRows.value.map((row) => row.id);
};

const clearReviewSelection = () => {
  reviewSelectedIds.value = [];
  reviewConfirmDelete.value = false;
};

const applyBulkReviewSchema = async () => {
  if (!reviewDeckId.value) {
    setStatus("warning", "Select a review deck first.");
    return;
  }
  if (!reviewSelectedIds.value.length) {
    setStatus("warning", "Select one or more cards.");
    return;
  }
  await runBusy("Applying bulk format", async () => {
    const response = await sidecarCall<{ updated: number; skipped: number }>("bulk_update_card_schema", {
      deck_id: reviewDeckId.value,
      card_ids: reviewSelectedIds.value,
      schema_key: reviewBulkSchemaKey.value,
    });
    setStatus(
      "success",
      `Updated ${response.updated} card(s); skipped ${response.skipped} duplicate word(s).`,
    );
    await refreshAllData();
  });
};

const deleteSelectedReviewCards = async () => {
  if (!reviewDeckId.value) {
    setStatus("warning", "Select a review deck first.");
    return;
  }
  if (!reviewSelectedIds.value.length) {
    setStatus("warning", "Select one or more cards.");
    return;
  }
  if (!reviewConfirmDelete.value) {
    setStatus("warning", "Enable delete confirmation first.");
    return;
  }
  await runBusy("Deleting review cards", async () => {
    const response = await sidecarCall<{ deleted: number }>("delete_deck_cards", {
      deck_id: reviewDeckId.value,
      card_ids: reviewSelectedIds.value,
    });
    setStatus("success", `Deleted ${response.deleted} card(s).`);
    clearReviewSelection();
    await refreshAllData();
  });
};

const saveSingleReviewCard = async () => {
  if (!reviewDeckId.value || !singleEdit.cardId) {
    setStatus("warning", "Select exactly one card first.");
    return;
  }
  await runBusy("Saving card changes", async () => {
    const response = await sidecarCall<{ updated: boolean }>("update_card", {
      deck_id: reviewDeckId.value,
      card_id: singleEdit.cardId,
      kanji: singleEdit.kanji,
      kana: singleEdit.kana,
      english: singleEdit.english,
      notes: singleEdit.notes,
      schema_key: singleEdit.schemaKey,
    });
    setStatus(
      response.updated ? "success" : "warning",
      response.updated
        ? "Card updated."
        : "Update skipped: duplicate word already exists for the selected format.",
    );
    await refreshAllData();
  });
};

const pickReviewMedia = async () => {
  await runBusy("Selecting replacement media", async () => {
    reviewReplaceMediaPaths.value = await pickPaths({
      multiple: true,
      title: "Select replacement media",
      filters: [{ name: "Media", extensions: ["png", "jpg", "jpeg", "webp", "mp4", "webm", "mov", "mp3", "wav", "m4a", "ogg"] }],
    });
  });
};

const replaceReviewMedia = async () => {
  if (!reviewDeckId.value || !singleEdit.cardId) {
    setStatus("warning", "Select exactly one card first.");
    return;
  }
  if (!reviewReplaceMediaPaths.value.length) {
    setStatus("warning", "Select media files first.");
    return;
  }
  await runBusy("Replacing card media", async () => {
    await sidecarCall("replace_card_media", {
      deck_id: reviewDeckId.value,
      card_id: singleEdit.cardId,
      replace_target: reviewReplaceTarget.value,
      media_type: reviewReplaceMediaType.value,
      media_paths: reviewReplaceMediaPaths.value,
    });
    setStatus("success", "Media replacement applied.");
    reviewReplaceMediaPaths.value = [];
    await refreshAllData();
  });
};

const previousRevisionCard = () => {
  if (!revisionRows.value.length) {
    setStatus("warning", "No cards available in the selected deck.");
    return;
  }
  revisionShowBack.value = false;
  if (revisionIndex.value <= 0) {
    revisionIndex.value = revisionRows.value.length - 1;
    return;
  }
  revisionIndex.value -= 1;
};

const nextRevisionCard = () => {
  if (!revisionRows.value.length) {
    setStatus("warning", "No cards available in the selected deck.");
    return;
  }
  revisionShowBack.value = false;
  if (revisionIndex.value >= revisionRows.value.length - 1) {
    revisionIndex.value = 0;
    return;
  }
  revisionIndex.value += 1;
};

const flipRevisionCard = () => {
  if (!revisionRows.value.length) {
    setStatus("warning", "No cards available in the selected deck.");
    return;
  }
  revisionShowBack.value = !revisionShowBack.value;
};

const speedBonusForSeconds = (elapsed: number) => {
  if (elapsed <= 2) return 6;
  if (elapsed <= 4) return 4;
  if (elapsed <= 6) return 2;
  if (elapsed <= 8) return 1;
  return 0;
};

const completePracticeRound = () => {
  practiceRoundActive.value = false;
  if (practiceRoundStartedAt.value > 0) {
    practiceRoundElapsedSeconds.value = Number((Date.now() / 1000 - practiceRoundStartedAt.value).toFixed(2));
  }
  practiceTeInput.value = "";
  practiceLastResultMessage.value = "Round complete.";
  setStatus(
    "success",
    `Game complete. Score ${practiceScore.value}. Correct ${practiceCorrectCount.value}, Incorrect ${practiceIncorrectCount.value}, Best streak ${practiceBestStreak.value}.`,
  );
};

const startPracticeRound = async () => {
  if (!contextDeckId.value) {
    setStatus("warning", "Select a context deck first.");
    return;
  }
  await runBusy("Starting game round", async () => {
    const response = await sidecarCall<{
      rows: PracticeRoundCard[];
      scoring: { base_correct_points: number; incorrect_penalty_points: number; bucket_labels: Record<string, string> };
    }>("get_practice_round", {
      deck_id: contextDeckId.value,
      mode: practiceMode.value,
    });
    practiceRoundCards.value = response.rows ?? [];
    if (!practiceRoundCards.value.length) {
      if (practiceMode.value === "verb_sort") {
        setStatus("warning", "No Ichidan/Godan verb cards found in this deck.");
      } else if (practiceMode.value === "adjective_sort") {
        setStatus("warning", "No い/な adjective cards found in this deck.");
      } else {
        setStatus("warning", "No verb cards with usable て-form data found in this deck.");
      }
      return;
    }
    practiceScoring.base_correct_points = response.scoring.base_correct_points;
    practiceScoring.incorrect_penalty_points = response.scoring.incorrect_penalty_points;
    practiceScoring.bucket_labels = response.scoring.bucket_labels;

    const nowSeconds = Date.now() / 1000;
    practiceRoundActive.value = true;
    practiceRoundIndex.value = 0;
    practiceRoundStartedAt.value = nowSeconds;
    practiceQuestionStartedAt.value = nowSeconds;
    practiceRoundElapsedSeconds.value = 0;
    practiceScore.value = 0;
    practiceCorrectCount.value = 0;
    practiceIncorrectCount.value = 0;
    practiceStreak.value = 0;
    practiceBestStreak.value = 0;
    practiceLastSpeedBonus.value = 0;
    practiceLastResultMessage.value = "";
    practiceTeInput.value = "";
    practiceAnswers.value = [];
    setStatus("success", `Started ${practiceMode.value} with ${practiceRoundCards.value.length} card(s).`);
  });
};

const stopPracticeRound = () => {
  if (!practiceRoundActive.value) {
    return;
  }
  practiceRoundActive.value = false;
  if (practiceRoundStartedAt.value > 0) {
    practiceRoundElapsedSeconds.value = Number((Date.now() / 1000 - practiceRoundStartedAt.value).toFixed(2));
  }
  practiceTeInput.value = "";
  practiceLastResultMessage.value = "Round stopped.";
};

const answerBucketRound = (selectedBucket: string) => {
  if (!practiceRoundActive.value) {
    setStatus("warning", "Start a game round first.");
    return;
  }
  const card = practiceCurrentCard.value;
  if (!card) {
    completePracticeRound();
    return;
  }
  const expectedBucket = String(card.expected ?? "");
  const nowSeconds = Date.now() / 1000;
  const elapsed = Math.max(0, nowSeconds - practiceQuestionStartedAt.value);
  const speedBonus = speedBonusForSeconds(elapsed);
  const correct = selectedBucket === expectedBucket;
  let deltaPoints = 0;

  if (correct) {
    practiceStreak.value += 1;
    practiceBestStreak.value = Math.max(practiceBestStreak.value, practiceStreak.value);
    const streakBonus = Math.min((practiceStreak.value - 1) * 2, 12);
    deltaPoints = practiceScoring.base_correct_points + speedBonus + streakBonus;
    practiceScore.value += deltaPoints;
    practiceCorrectCount.value += 1;
    practiceLastSpeedBonus.value = speedBonus;
    practiceLastResultMessage.value = `Correct. +${deltaPoints} (speed +${speedBonus}, streak ${practiceStreak.value}).`;
  } else {
    practiceStreak.value = 0;
    deltaPoints = -practiceScoring.incorrect_penalty_points;
    practiceScore.value = Math.max(0, practiceScore.value + deltaPoints);
    practiceIncorrectCount.value += 1;
    practiceLastSpeedBonus.value = 0;
    practiceLastResultMessage.value = `Incorrect. Expected ${practiceScoring.bucket_labels[expectedBucket] ?? expectedBucket}. ${deltaPoints} points.`;
  }

  practiceAnswers.value = [
    ...practiceAnswers.value,
    {
      mode: practiceMode.value,
      prompt: String(card.prompt ?? ""),
      hint: String(card.hint ?? ""),
      expected: expectedBucket,
      selected: selectedBucket,
      correct,
      elapsed_seconds: Number(elapsed.toFixed(2)),
      delta_points: deltaPoints,
    },
  ];

  practiceRoundIndex.value += 1;
  if (practiceRoundIndex.value >= practiceRoundCards.value.length) {
    completePracticeRound();
    return;
  }
  practiceQuestionStartedAt.value = Date.now() / 1000;
};

const submitTeFormAnswer = () => {
  if (!practiceRoundActive.value) {
    setStatus("warning", "Start a game round first.");
    return;
  }
  const card = practiceCurrentCard.value;
  if (!card) {
    completePracticeRound();
    return;
  }
  const submittedDisplay = practiceTeInput.value.trim();
  const submittedNormalized = submittedDisplay.replace(/\s+/g, "");
  if (!submittedNormalized) {
    setStatus("warning", "Type a て-form answer first.");
    return;
  }

  const acceptedAnswers = (card.accepted_answers ?? []).map((value) => String(value ?? ""));
  const expectedDisplay = String(card.expected_display ?? card.expected ?? "");
  const nowSeconds = Date.now() / 1000;
  const elapsed = Math.max(0, nowSeconds - practiceQuestionStartedAt.value);
  const speedBonus = speedBonusForSeconds(elapsed);
  const correct = acceptedAnswers.includes(submittedNormalized);
  let deltaPoints = 0;

  if (correct) {
    practiceStreak.value += 1;
    practiceBestStreak.value = Math.max(practiceBestStreak.value, practiceStreak.value);
    const streakBonus = Math.min((practiceStreak.value - 1) * 2, 12);
    deltaPoints = practiceScoring.base_correct_points + speedBonus + streakBonus;
    practiceScore.value += deltaPoints;
    practiceCorrectCount.value += 1;
    practiceLastSpeedBonus.value = speedBonus;
    practiceLastResultMessage.value = `Correct. +${deltaPoints} (speed +${speedBonus}, streak ${practiceStreak.value}).`;
  } else {
    practiceStreak.value = 0;
    deltaPoints = -practiceScoring.incorrect_penalty_points;
    practiceScore.value = Math.max(0, practiceScore.value + deltaPoints);
    practiceIncorrectCount.value += 1;
    practiceLastSpeedBonus.value = 0;
    practiceLastResultMessage.value = `Incorrect. Expected ${expectedDisplay}. ${deltaPoints} points.`;
  }

  practiceAnswers.value = [
    ...practiceAnswers.value,
    {
      mode: "te_form",
      prompt: String(card.prompt ?? ""),
      hint: String(card.hint ?? ""),
      expected: expectedDisplay,
      selected: submittedDisplay,
      correct,
      elapsed_seconds: Number(elapsed.toFixed(2)),
      delta_points: deltaPoints,
    },
  ];

  practiceTeInput.value = "";
  practiceRoundIndex.value += 1;
  if (practiceRoundIndex.value >= practiceRoundCards.value.length) {
    completePracticeRound();
    return;
  }
  practiceQuestionStartedAt.value = Date.now() / 1000;
};

const pickScanImages = async () => {
  await runBusy("Selecting scan images", async () => {
    scanImagePaths.value = await pickPaths({
      multiple: true,
      title: "Select image files to scan",
      filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp"] }],
    });
  });
};

const runImageScan = async () => {
  if (!scanDeckId.value) {
    setStatus("warning", "Select a scan destination deck.");
    return;
  }
  if (!scanImagePaths.value.length) {
    setStatus("warning", "Pick one or more images first.");
    return;
  }
  await runBusy("Scanning images", async () => {
    const response = await sidecarCall<{
      summary: string;
      preview_rows: typeof scanPreviewRows.value;
      errors: string[];
    }>("scan_images", {
      deck_id: scanDeckId.value,
      image_paths: scanImagePaths.value,
      schema_key: scanSchemaKey.value,
      word_form: scanWordForm.value,
      tags: scanTags.value,
    });
    scanSummary.value = response.summary ?? "";
    scanPreviewRows.value = response.preview_rows ?? [];
    scanErrors.value = response.errors ?? [];
    setStatus("success", "Image scan complete.");
    await refreshAllData();
  });
};

const pickCsvFile = async () => {
  await runBusy("Selecting CSV file", async () => {
    const selected = await pickPaths({
      multiple: false,
      title: "Select CSV file",
      filters: [{ name: "CSV", extensions: ["csv"] }],
    });
    importCsvPath.value = selected[0] ?? "";
  });
};

const runCsvImport = async () => {
  if (!importDeckId.value) {
    setStatus("warning", "Select an import destination deck.");
    return;
  }
  if (!importCsvPath.value) {
    setStatus("warning", "Pick a CSV file first.");
    return;
  }
  await runBusy("Importing CSV", async () => {
    const response = await sidecarCall<{ added: number; skipped: number }>("import_csv", {
      deck_id: importDeckId.value,
      csv_path: importCsvPath.value,
    });
    importCsvResult.value = `Added ${response.added} card(s), skipped ${response.skipped}.`;
    setStatus("success", importCsvResult.value);
    await refreshAllData();
  });
};

const runDeckExport = async () => {
  if (!exportDeckId.value) {
    setStatus("warning", "Select an export deck.");
    return;
  }
  await runBusy("Exporting deck package", async () => {
    const response = await sidecarCall<{ export_path: string }>("export_deck", {
      deck_id: exportDeckId.value,
    });
    exportPath.value = response.export_path ?? "";
    setStatus("success", `Deck exported to ${exportPath.value}`);
  });
};

const createCollection = async () => {
  if (!createCollectionName.value.trim()) {
    setStatus("warning", "Enter a collection name.");
    return;
  }
  await runBusy("Creating collection", async () => {
    await sidecarCall("create_collection", { name: createCollectionName.value });
    createCollectionName.value = "";
    setStatus("success", "Collection created.");
    await refreshAllData();
  });
};

const renameCollection = async () => {
  if (!renameCollectionId.value) {
    setStatus("warning", "Select a collection.");
    return;
  }
  if (!renameCollectionName.value.trim()) {
    setStatus("warning", "Enter a new collection name.");
    return;
  }
  await runBusy("Renaming collection", async () => {
    await sidecarCall("rename_collection", {
      collection_id: renameCollectionId.value,
      name: renameCollectionName.value,
    });
    renameCollectionName.value = "";
    setStatus("success", "Collection renamed.");
    await refreshAllData();
  });
};

const createDeck = async () => {
  if (!createDeckCollectionId.value) {
    setStatus("warning", "Select a collection first.");
    return;
  }
  if (!createDeckName.value.trim()) {
    setStatus("warning", "Enter a deck name.");
    return;
  }
  await runBusy("Creating deck", async () => {
    await sidecarCall("create_deck", {
      collection_id: createDeckCollectionId.value,
      name: createDeckName.value,
    });
    createDeckName.value = "";
    setStatus("success", "Deck created.");
    await refreshAllData();
  });
};

const renameDeck = async () => {
  if (!renameDeckId.value) {
    setStatus("warning", "Select a deck first.");
    return;
  }
  if (!renameDeckName.value.trim()) {
    setStatus("warning", "Enter a new deck name.");
    return;
  }
  await runBusy("Renaming deck", async () => {
    await sidecarCall("rename_deck", {
      deck_id: renameDeckId.value,
      name: renameDeckName.value,
    });
    renameDeckName.value = "";
    setStatus("success", "Deck renamed.");
    await refreshAllData();
  });
};

watch(
  [reviewSelectedIds, reviewRows],
  () => {
    if (reviewSelectedIds.value.length !== 1) {
      singleEdit.cardId = "";
      singleEdit.kanji = "";
      singleEdit.kana = "";
      singleEdit.english = "";
      singleEdit.notes = "";
      singleEdit.schemaKey = cardSchemas.value[0]?.key ?? "kana_kanji_front_english_back";
      return;
    }
    const selected = reviewRows.value.find((row) => row.id === reviewSelectedIds.value[0]);
    if (!selected) {
      singleEdit.cardId = "";
      return;
    }
    singleEdit.cardId = selected.id;
    singleEdit.kanji = selected.kanji;
    singleEdit.kana = selected.kana;
    singleEdit.english = selected.english;
    singleEdit.notes = selected.notes;
    singleEdit.schemaKey = selected.schema_key;
  },
  { immediate: true, deep: true },
);

watch(
  contextDeckId,
  async () => {
    if (!contextDeckId.value) {
      return;
    }
    if (!reviewDeckId.value) reviewDeckId.value = contextDeckId.value;
    if (!dictionaryDeckId.value) dictionaryDeckId.value = contextDeckId.value;
    if (!manualDeckId.value) manualDeckId.value = contextDeckId.value;
    if (!globalDestinationDeckId.value) globalDestinationDeckId.value = contextDeckId.value;
    if (!scanDeckId.value) scanDeckId.value = contextDeckId.value;
    if (!importDeckId.value) importDeckId.value = contextDeckId.value;
    if (!exportDeckId.value) exportDeckId.value = contextDeckId.value;
    await loadRevisionCards();
  },
  { immediate: false },
);

onMounted(async () => {
  if (!isTauriRuntime()) {
    setStatus("warning", "Run this interface via `npm run tauri:dev` to enable the Python sidecar.");
    return;
  }
  await runBusy("Loading app", async () => {
    await refreshAllData();
    clearStatus();
  });
});
</script>

<template>
  <UApp>
    <NuxtRouteAnnouncer />
    <div class="app-shell">
      <header class="hero">
        <div>
          <h1>{{ appTitle }} Desktop</h1>
          <p>Nuxt UI + Tauri + Python sidecar. Offline-first workflow with dictionary, deck management, revision, games, scan, import, and export.</p>
        </div>
        <div class="toolbar">
          <div class="field">
            <label>Context Scope</label>
            <select v-model="cardsScope">
              <option value="deck">Deck</option>
              <option value="global">Global Pool</option>
            </select>
          </div>
          <div class="field" style="min-width: 300px;">
            <label>Context Deck</label>
            <select v-model="contextDeckId">
              <option value="">Select deck...</option>
              <option v-for="deck in decks" :key="deck.id" :value="deck.id">
                {{ deck.label }}
              </option>
            </select>
          </div>
          <UButton
            color="neutral"
            variant="soft"
            :disabled="Boolean(busyAction)"
            @click="refreshAllData"
          >
            Refresh
          </UButton>
        </div>
      </header>

      <div class="panel" v-if="statusMessage">
        <div class="toolbar">
          <strong :class="statusClass">{{ statusLevel.toUpperCase() }}</strong>
          <span>{{ statusMessage }}</span>
          <span class="muted" v-if="busyAction">| Running: {{ busyAction }}</span>
        </div>
      </div>

      <div class="panel">
        <div class="tabs">
          <UButton
            v-for="tab in tabs"
            :key="tab.key"
            :variant="activeTab === tab.key ? 'solid' : 'soft'"
            :color="activeTab === tab.key ? 'primary' : 'neutral'"
            size="sm"
            @click="activeTab = tab.key"
          >
            {{ tab.label }}
          </UButton>
        </div>
      </div>

      <section v-if="activeTab === 'overview'" class="grid">
        <div class="panel">
          <h2>Workspace Snapshot</h2>
          <p class="muted">Current context: {{ selectedContextDeckLabel }}</p>
          <div class="stats">
            <div class="stat">
              <strong>{{ dashboard.collection_count }}</strong>
              <span>Collections</span>
            </div>
            <div class="stat">
              <strong>{{ dashboard.deck_count }}</strong>
              <span>Decks</span>
            </div>
            <div class="stat">
              <strong>{{ dashboard.card_count }}</strong>
              <span>Deck Cards</span>
            </div>
            <div class="stat">
              <strong>{{ dashboard.global_card_count }}</strong>
              <span>Global Cards</span>
            </div>
          </div>
        </div>

        <div class="panel">
          <h2>Collection + Deck Management</h2>
          <div class="grid grid-3">
            <div class="field">
              <label>Create Collection</label>
              <input v-model="createCollectionName" placeholder="Collection name" />
              <UButton size="sm" variant="solid" :disabled="Boolean(busyAction)" @click="createCollection">
                Create Collection
              </UButton>
            </div>

            <div class="field">
              <label>Rename Collection</label>
              <select v-model="renameCollectionId">
                <option value="">Select collection...</option>
                <option v-for="collection in collections" :key="collection.id" :value="collection.id">
                  {{ collection.name }}
                </option>
              </select>
              <input v-model="renameCollectionName" placeholder="New name" />
              <UButton size="sm" variant="solid" color="warning" :disabled="Boolean(busyAction)" @click="renameCollection">
                Rename Collection
              </UButton>
            </div>

            <div class="field">
              <label>Create Deck</label>
              <select v-model="createDeckCollectionId">
                <option value="">Select collection...</option>
                <option v-for="collection in collections" :key="collection.id" :value="collection.id">
                  {{ collection.name }}
                </option>
              </select>
              <input v-model="createDeckName" placeholder="Deck name" />
              <UButton size="sm" variant="solid" :disabled="Boolean(busyAction)" @click="createDeck">
                Create Deck
              </UButton>
            </div>
          </div>

          <div class="grid grid-2" style="margin-top: 0.9rem;">
            <div class="field">
              <label>Rename Deck</label>
              <select v-model="renameDeckId">
                <option value="">Select deck...</option>
                <option v-for="deck in decks" :key="deck.id" :value="deck.id">
                  {{ deck.label }}
                </option>
              </select>
              <input v-model="renameDeckName" placeholder="New deck name" />
              <UButton size="sm" variant="solid" color="warning" :disabled="Boolean(busyAction)" @click="renameDeck">
                Rename Deck
              </UButton>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Collection</th>
                    <th>Deck</th>
                    <th>Cards</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="!dashboard.rows.length">
                    <td colspan="3" class="muted">No deck rows yet.</td>
                  </tr>
                  <tr v-for="row in dashboard.rows" :key="`${row.collection_name}-${row.deck_name}`">
                    <td>{{ row.collection_name }}</td>
                    <td>{{ row.deck_name }}</td>
                    <td>{{ row.card_count }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      <section v-if="activeTab === 'dictionary'" class="grid">
        <div class="panel">
          <h2>Dictionary Search</h2>
          <div class="grid grid-2">
            <div class="toolbar">
              <div class="field" style="min-width: 320px;">
                <label>Query</label>
                <input
                  v-model="dictionaryQuery"
                  placeholder="Search by kanji, kana, or expression"
                  @keydown.enter.prevent="searchDictionary"
                />
              </div>
              <UButton :disabled="Boolean(busyAction)" @click="searchDictionary">Search</UButton>
              <UButton variant="soft" color="neutral" :disabled="Boolean(busyAction)" @click="dictionaryQuery = ''; dictionaryResults = []; dictionarySelectedIds = []">
                Clear
              </UButton>
              <UButton variant="soft" color="neutral" :disabled="Boolean(busyAction)" @click="selectAllDictionary">
                Select All
              </UButton>
              <UButton variant="soft" color="neutral" :disabled="Boolean(busyAction)" @click="clearDictionarySelection">
                Clear Selection
              </UButton>
            </div>

            <div class="grid grid-3">
              <div class="field">
                <label>Destination</label>
                <select v-model="dictionaryDestination">
                  <option value="deck">Deck</option>
                  <option value="global">Global Pool</option>
                </select>
              </div>
              <div class="field" v-if="dictionaryDestination === 'deck'">
                <label>Deck</label>
                <select v-model="dictionaryDeckId">
                  <option value="">Select deck...</option>
                  <option v-for="deck in decks" :key="deck.id" :value="deck.id">
                    {{ deck.label }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label>Schema</label>
                <select v-model="dictionarySchemaKey">
                  <option v-for="schema in cardSchemas" :key="schema.key" :value="schema.key">
                    {{ schema.label }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label>Word Form</label>
                <select v-model="dictionaryWordForm">
                  <option v-for="form in verbForms" :key="form.key" :value="form.key">
                    {{ form.label }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label>Tags (comma-separated)</label>
                <input v-model="dictionaryTags" placeholder="japanese,jamdict" />
              </div>
              <div class="field">
                <label>English Override (optional)</label>
                <input v-model="dictionaryEnglishOverride" placeholder="Leave empty to use dictionary gloss" />
              </div>
            </div>
          </div>

          <div class="field" style="margin-top: 0.7rem;">
            <label>Shared Notes</label>
            <textarea v-model="dictionaryNotes" placeholder="Optional notes added to all selected entries"></textarea>
          </div>

          <div class="toolbar" style="margin-top: 0.6rem;">
            <UButton :disabled="Boolean(busyAction)" @click="addSelectedDictionaryEntries">
              Add Selected Entries
            </UButton>
            <UButton variant="soft" color="neutral" :disabled="Boolean(busyAction)" @click="prefillManualFromFirstDictionarySelection">
              Prefill Manual Builder
            </UButton>
          </div>
        </div>

        <div class="panel">
          <h3>Results</h3>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style="width: 44px;">Sel</th>
                  <th>Word</th>
                  <th>Reading</th>
                  <th>Meaning</th>
                  <th>POS</th>
                  <th style="width: 260px;">Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!dictionaryResults.length">
                  <td colspan="6" class="muted">No dictionary results loaded.</td>
                </tr>
                <tr v-for="entry in dictionaryResults" :key="entry.entry_id">
                  <td>
                    <input
                      type="checkbox"
                      :checked="dictionarySelectedIds.includes(entry.entry_id)"
                      @change="toggleId(dictionarySelectedIds as any, entry.entry_id)"
                    />
                  </td>
                  <td>{{ entry.headword }}</td>
                  <td>{{ entry.reading }}</td>
                  <td>{{ entry.english }}</td>
                  <td>{{ (entry.pos_labels || []).slice(0, 2).join(", ") }}</td>
                  <td>
                    <div class="toolbar">
                      <UButton size="xs" :disabled="Boolean(busyAction)" @click="quickAddDictionaryEntry(entry.entry_id, 'deck')">
                        Quick Add Deck
                      </UButton>
                      <UButton size="xs" variant="soft" :disabled="Boolean(busyAction)" @click="quickAddDictionaryEntry(entry.entry_id, 'global')">
                        Quick Add Global
                      </UButton>
                      <UButton size="xs" variant="soft" color="neutral" :disabled="Boolean(busyAction)" @click="prefillManualFromDictionary(entry)">
                        Use In Builder
                      </UButton>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section v-if="activeTab === 'builder'" class="grid grid-2">
        <div class="panel">
          <h2>Manual Card Builder</h2>
          <div class="grid grid-2">
            <div class="field">
              <label>Destination</label>
              <select v-model="manualDestination">
                <option value="global">Global Pool</option>
                <option value="deck">Deck</option>
              </select>
            </div>
            <div class="field" v-if="manualDestination === 'deck'">
              <label>Deck</label>
              <select v-model="manualDeckId">
                <option value="">Select deck...</option>
                <option v-for="deck in decks" :key="deck.id" :value="deck.id">
                  {{ deck.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>Schema</label>
              <select v-model="manualSchemaKey">
                <option v-for="schema in cardSchemas" :key="schema.key" :value="schema.key">
                  {{ schema.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>Word Kind</label>
              <select v-model="manualWordKind">
                <option v-for="type in verbTypes" :key="type.key" :value="type.key">
                  {{ type.label }}
                </option>
              </select>
            </div>
            <div class="field" v-if="manualIsVerb">
              <label>Deck Word Form</label>
              <select v-model="manualWordForm">
                <option v-for="form in verbForms" :key="form.key" :value="form.key">
                  {{ form.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>Word (Kanji)</label>
              <input v-model="manualKanji" placeholder="食べる" />
            </div>
            <div class="field">
              <label>Reading (Kana)</label>
              <input v-model="manualKana" placeholder="たべる" />
            </div>
            <div class="field">
              <label>English</label>
              <input v-model="manualEnglish" placeholder="to eat" />
            </div>
          </div>

          <div class="field" style="margin-top: 0.6rem;">
            <label>Notes</label>
            <textarea v-model="manualNotes" placeholder="Optional notes or sentence context"></textarea>
          </div>

          <div class="grid grid-2" style="margin-top: 0.6rem;">
            <div class="field">
              <label>Tags (comma-separated)</label>
              <input v-model="manualTags" placeholder="manual,verbs" />
            </div>
            <div class="field">
              <label>Media</label>
              <div class="toolbar">
                <UButton size="sm" variant="soft" :disabled="Boolean(busyAction)" @click="pickManualMedia">
                  Pick Media Files
                </UButton>
                <span class="muted">{{ manualMediaPaths.length }} selected</span>
              </div>
            </div>
          </div>

          <div class="field" style="margin-top: 0.6rem;">
            <label>Dictionary Metadata (optional)</label>
            <div class="grid grid-2">
              <input v-model="manualDictionaryEntryId" placeholder="JMDict entry id" />
              <input v-model="manualDictionaryHeadword" placeholder="Dictionary headword" />
              <input v-model="manualDictionaryReading" placeholder="Dictionary reading" />
              <input v-model="manualDictionaryGloss" placeholder="Dictionary gloss" />
              <input v-model="manualDictionaryPos" placeholder="Dictionary POS labels" />
              <input v-model="manualVerbType" placeholder="verb_type (ichidan/godan/...)" />
            </div>
          </div>

          <div class="toolbar" style="margin-top: 0.7rem;">
            <UButton :disabled="Boolean(busyAction)" @click="generateManualForms">
              Generate Forms
            </UButton>
            <UButton variant="soft" color="neutral" :disabled="Boolean(busyAction)" @click="saveManualCard">
              Save Card
            </UButton>
          </div>
          <ul class="file-list" v-if="manualMediaPaths.length">
            <li v-for="path in manualMediaPaths" :key="path" class="mono">{{ path }}</li>
          </ul>
        </div>

        <div class="panel">
          <h3>Word Forms</h3>
          <p class="muted">Edit generated forms if needed before saving.</p>
          <div class="grid">
            <div class="grid grid-2">
              <div class="field">
                <label>Dictionary Form (Word)</label>
                <input v-model="manualForms.dictionary.word" />
              </div>
              <div class="field">
                <label>Dictionary Form (Reading)</label>
                <input v-model="manualForms.dictionary.reading" />
              </div>
              <div class="field">
                <label>Masu Form (Word)</label>
                <input v-model="manualForms.masu.word" />
              </div>
              <div class="field">
                <label>Masu Form (Reading)</label>
                <input v-model="manualForms.masu.reading" />
              </div>
              <div class="field">
                <label>Te Form (Word)</label>
                <input v-model="manualForms.te.word" />
              </div>
              <div class="field">
                <label>Te Form (Reading)</label>
                <input v-model="manualForms.te.reading" />
              </div>
              <div class="field">
                <label>Past Form (Word)</label>
                <input v-model="manualForms.past.word" />
              </div>
              <div class="field">
                <label>Past Form (Reading)</label>
                <input v-model="manualForms.past.reading" />
              </div>
              <div class="field">
                <label>Negative Form (Word)</label>
                <input v-model="manualForms.negative.word" />
              </div>
              <div class="field">
                <label>Negative Form (Reading)</label>
                <input v-model="manualForms.negative.reading" />
              </div>
              <div class="field">
                <label>Potential Form (Word)</label>
                <input v-model="manualForms.potential.word" />
              </div>
              <div class="field">
                <label>Potential Form (Reading)</label>
                <input v-model="manualForms.potential.reading" />
              </div>
              <div class="field">
                <label>Passive Form (Word)</label>
                <input v-model="manualForms.passive.word" />
              </div>
              <div class="field">
                <label>Passive Form (Reading)</label>
                <input v-model="manualForms.passive.reading" />
              </div>
              <div class="field">
                <label>Causative Form (Word)</label>
                <input v-model="manualForms.causative.word" />
              </div>
              <div class="field">
                <label>Causative Form (Reading)</label>
                <input v-model="manualForms.causative.reading" />
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-if="activeTab === 'pool'" class="grid">
        <div class="panel">
          <h2>Global Pool Operations</h2>
          <div class="grid grid-3">
            <div class="field">
              <label>Import Source Deck -> Global Pool</label>
              <select v-model="globalSourceDeckId">
                <option value="">Select deck...</option>
                <option v-for="deck in decks" :key="deck.id" :value="deck.id">
                  {{ deck.label }}
                </option>
              </select>
              <UButton size="sm" :disabled="Boolean(busyAction)" @click="importSourceDeckToGlobalPool">
                Import Source Deck
              </UButton>
            </div>
            <div class="field">
              <label>Search Global Cards</label>
              <input
                v-model="globalSearchText"
                placeholder="Search dictionary or inflected forms (e.g. て/ます)"
                @keydown.enter.prevent="loadGlobalCards"
              />
              <div class="toolbar">
                <UButton size="sm" variant="soft" :disabled="Boolean(busyAction)" @click="loadGlobalCards">
                  Search
                </UButton>
                <UButton size="sm" variant="soft" color="neutral" :disabled="Boolean(busyAction)" @click="globalSearchText = ''; loadGlobalCards()">
                  Clear
                </UButton>
              </div>
            </div>
            <div class="field">
              <label>Selected</label>
              <div class="muted">{{ globalSelectedIds.length }} card(s) selected</div>
              <div class="toolbar">
                <UButton size="sm" variant="soft" color="neutral" :disabled="Boolean(busyAction)" @click="globalSelectedIds = globalRows.map((row) => row.id)">
                  Select All Visible
                </UButton>
                <UButton size="sm" variant="soft" color="neutral" :disabled="Boolean(busyAction)" @click="globalSelectedIds = []">
                  Clear Selection
                </UButton>
              </div>
            </div>
          </div>

          <div class="grid grid-3" style="margin-top: 0.7rem;">
            <div class="field">
              <label>Destination Deck</label>
              <select v-model="globalDestinationDeckId">
                <option value="">Select deck...</option>
                <option v-for="deck in decks" :key="deck.id" :value="deck.id">
                  {{ deck.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>Destination Schema</label>
              <select v-model="globalDestinationSchemaKey">
                <option v-for="schema in cardSchemas" :key="schema.key" :value="schema.key">
                  {{ schema.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>Word Form</label>
              <select v-model="globalDestinationWordForm">
                <option v-for="form in verbForms" :key="form.key" :value="form.key">
                  {{ form.label }}
                </option>
              </select>
            </div>
          </div>

          <div class="field" style="margin-top: 0.65rem;">
            <label>Import Tags</label>
            <input v-model="globalImportTags" placeholder="global_pool" />
          </div>

          <div class="toolbar" style="margin-top: 0.6rem;">
            <UButton :disabled="Boolean(busyAction)" @click="importSelectedGlobalToDeck">
              Import Selected To Deck
            </UButton>
            <UButton color="error" variant="soft" :disabled="Boolean(busyAction)" @click="deleteSelectedGlobalCards">
              Delete Selected Global Cards
            </UButton>
          </div>
        </div>

        <div class="panel">
          <h3>Global Cards</h3>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style="width: 44px;">Sel</th>
                  <th>Word</th>
                  <th>Reading</th>
                  <th>English</th>
                  <th>Forms</th>
                  <th>Dictionary</th>
                  <th>Tags</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!globalRows.length">
                  <td colspan="7" class="muted">No global cards to display.</td>
                </tr>
                <tr v-for="row in globalRows" :key="row.id">
                  <td>
                    <input
                      type="checkbox"
                      :checked="globalSelectedIds.includes(row.id)"
                      @change="toggleId(globalSelectedIds as any, row.id)"
                    />
                  </td>
                  <td>{{ row.kanji }}</td>
                  <td>{{ row.kana }}</td>
                  <td>{{ row.english }}</td>
                  <td>
                    <div class="chip-list">
                      <span class="chip" v-if="row.kanji_masu">{{ row.kanji_masu }}</span>
                      <span class="chip" v-if="row.kanji_te">{{ row.kanji_te }}</span>
                      <span class="chip" v-if="row.kanji_past">{{ row.kanji_past }}</span>
                      <span class="chip" v-if="row.kanji_negative">{{ row.kanji_negative }}</span>
                    </div>
                  </td>
                  <td class="mono">{{ row.dictionary_entry_id || "-" }}</td>
                  <td>
                    <div class="chip-list">
                      <span class="chip" v-for="tag in row.tags" :key="`${row.id}-${tag}`">{{ tag }}</span>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section v-if="activeTab === 'review'" class="grid">
        <div class="panel">
          <h2>Deck Cards Review</h2>
          <div class="grid grid-3">
            <div class="field">
              <label>Review Deck</label>
              <select v-model="reviewDeckId" @change="loadReviewCards">
                <option value="">Select deck...</option>
                <option v-for="deck in decks" :key="deck.id" :value="deck.id">
                  {{ deck.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>Search</label>
              <input
                v-model="reviewSearchText"
                placeholder="Search by dictionary or inflected form"
                @keydown.enter.prevent="loadReviewCards"
              />
            </div>
            <div class="field">
              <label>Actions</label>
              <div class="toolbar">
                <UButton size="sm" variant="soft" :disabled="Boolean(busyAction)" @click="loadReviewCards">
                  Search
                </UButton>
                <UButton size="sm" variant="soft" color="neutral" :disabled="Boolean(busyAction)" @click="selectAllReviewRows">
                  Select All
                </UButton>
                <UButton size="sm" variant="soft" color="neutral" :disabled="Boolean(busyAction)" @click="clearReviewSelection">
                  Clear
                </UButton>
              </div>
            </div>
          </div>

          <div class="table-wrap" style="margin-top: 0.65rem;">
            <table>
              <thead>
                <tr>
                  <th style="width: 44px;">Sel</th>
                  <th>#</th>
                  <th>Word</th>
                  <th>Reading</th>
                  <th>English</th>
                  <th>Schema</th>
                  <th>Form</th>
                  <th>Dictionary ID</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!reviewRows.length">
                  <td colspan="8" class="muted">No deck cards to display.</td>
                </tr>
                <tr v-for="row in reviewRows" :key="row.id">
                  <td>
                    <input
                      type="checkbox"
                      :checked="reviewSelectedIds.includes(row.id)"
                      @change="toggleId(reviewSelectedIds as any, row.id)"
                    />
                  </td>
                  <td>{{ row.index }}</td>
                  <td>{{ row.kanji }}</td>
                  <td>{{ row.kana }}</td>
                  <td>{{ row.english }}</td>
                  <td>{{ row.schema_label }}</td>
                  <td>{{ row.word_form }}</td>
                  <td class="mono">{{ row.dictionary_entry_id || "-" }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="panel">
          <h3>Bulk + Single Edit</h3>
          <div class="grid grid-2">
            <div class="field">
              <label>Bulk Schema</label>
              <select v-model="reviewBulkSchemaKey">
                <option v-for="schema in cardSchemas" :key="schema.key" :value="schema.key">
                  {{ schema.label }}
                </option>
              </select>
              <UButton size="sm" :disabled="Boolean(busyAction)" @click="applyBulkReviewSchema">
                Apply Schema To Selected
              </UButton>
            </div>
            <div class="field">
              <label>Delete Selected</label>
              <div class="toolbar">
                <label class="muted">
                  <input type="checkbox" v-model="reviewConfirmDelete" />
                  Confirm delete
                </label>
                <UButton size="sm" color="error" variant="soft" :disabled="Boolean(busyAction)" @click="deleteSelectedReviewCards">
                  Delete Selected Cards
                </UButton>
              </div>
            </div>
          </div>

          <div class="grid grid-2" style="margin-top: 0.75rem;">
            <div class="field">
              <label>Single Card Edit (requires exactly one selected)</label>
              <input v-model="singleEdit.kanji" placeholder="Kanji" />
              <input v-model="singleEdit.kana" placeholder="Kana" />
              <input v-model="singleEdit.english" placeholder="English" />
              <textarea v-model="singleEdit.notes" placeholder="Notes"></textarea>
              <select v-model="singleEdit.schemaKey">
                <option v-for="schema in cardSchemas" :key="schema.key" :value="schema.key">
                  {{ schema.label }}
                </option>
              </select>
              <UButton size="sm" :disabled="Boolean(busyAction)" @click="saveSingleReviewCard">
                Save Single Card
              </UButton>
            </div>

            <div class="field">
              <label>Replace Card Media</label>
              <select v-model="reviewReplaceTarget">
                <option value="english">Replace English text with media tag</option>
                <option value="kana">Replace Kana text with media tag</option>
                <option value="kanji">Replace Kanji text with media tag</option>
                <option value="none">Do not replace text</option>
              </select>
              <select v-model="reviewReplaceMediaType">
                <option value="image">Image</option>
                <option value="audio">Audio</option>
                <option value="video">Video</option>
              </select>
              <div class="toolbar">
                <UButton size="sm" variant="soft" :disabled="Boolean(busyAction)" @click="pickReviewMedia">
                  Pick Media Files
                </UButton>
                <span class="muted">{{ reviewReplaceMediaPaths.length }} selected</span>
              </div>
              <UButton size="sm" variant="soft" color="neutral" :disabled="Boolean(busyAction)" @click="replaceReviewMedia">
                Apply Media Replacement
              </UButton>
              <ul class="file-list" v-if="reviewReplaceMediaPaths.length">
                <li v-for="path in reviewReplaceMediaPaths" :key="path" class="mono">{{ path }}</li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      <section v-if="activeTab === 'practice'" class="grid grid-2">
        <div class="panel">
          <h2>Revision Mode</h2>
          <p class="muted">Deck: {{ selectedContextDeckLabel }}</p>
          <div class="revision-card">
            <div class="muted">
              {{ revisionProgressLabel }} | {{ revisionShowBack ? "Back" : "Front" }}
            </div>
            <div class="revision-face">{{ revisionFaceText || "No cards available." }}</div>
            <div class="muted" v-if="currentRevisionCard">
              {{ currentRevisionCard.schema_label }} | Word form: {{ currentRevisionCard.word_form }}
            </div>
            <div class="muted" v-if="currentRevisionCard?.notes">
              Notes: {{ currentRevisionCard.notes }}
            </div>
          </div>
          <div class="toolbar" style="margin-top: 0.7rem;">
            <UButton size="sm" variant="soft" :disabled="Boolean(busyAction)" @click="previousRevisionCard">
              Previous
            </UButton>
            <UButton size="sm" variant="solid" :disabled="Boolean(busyAction)" @click="flipRevisionCard">
              Flip
            </UButton>
            <UButton size="sm" variant="soft" :disabled="Boolean(busyAction)" @click="nextRevisionCard">
              Next
            </UButton>
            <UButton size="sm" variant="soft" color="neutral" :disabled="Boolean(busyAction)" @click="loadRevisionCards">
              Reload Cards
            </UButton>
          </div>
        </div>

        <div class="panel">
          <h2>Practice Games</h2>
          <div class="grid grid-2">
            <div class="field">
              <label>Game Mode</label>
              <select v-model="practiceMode">
                <option v-for="mode in practiceModeOptions" :key="mode.key" :value="mode.key">
                  {{ mode.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>Round Controls</label>
              <div class="toolbar">
                <UButton size="sm" :disabled="Boolean(busyAction) || practiceRoundActive" @click="startPracticeRound">
                  Start Round
                </UButton>
                <UButton size="sm" variant="soft" color="neutral" :disabled="Boolean(busyAction) || !practiceRoundActive" @click="stopPracticeRound">
                  Stop Round
                </UButton>
              </div>
            </div>
          </div>

          <div class="game-pad" style="margin-top: 0.7rem;">
            <div class="muted">{{ practiceProgressLabel }}</div>
            <div style="font-size: 1.2rem; font-weight: 700;">
              {{ practiceCurrentCard?.prompt || "No active prompt." }}
            </div>
            <div class="muted">
              {{ practiceCurrentCard?.hint || "" }}
            </div>
            <div class="toolbar" style="margin-top: 0.6rem;" v-if="practiceRoundActive && practiceMode !== 'te_form'">
              <UButton size="sm" @click="answerBucketRound(practiceMode === 'verb_sort' ? 'ichidan' : 'i_adj')">
                {{ practiceMode === "verb_sort" ? "Ichidan" : "I-adjective (い)" }}
              </UButton>
              <UButton size="sm" variant="soft" @click="answerBucketRound(practiceMode === 'verb_sort' ? 'godan' : 'na_adj')">
                {{ practiceMode === "verb_sort" ? "Godan" : "Na-adjective (な)" }}
              </UButton>
            </div>
            <div class="toolbar" style="margin-top: 0.6rem;" v-if="practiceRoundActive && practiceMode === 'te_form'">
              <input
                v-model="practiceTeInput"
                placeholder="Type the correct て-form"
                @keydown.enter.prevent="submitTeFormAnswer"
                style="min-width: 260px;"
              />
              <UButton size="sm" @click="submitTeFormAnswer">Submit</UButton>
            </div>
            <div class="muted" style="margin-top: 0.55rem;">
              {{ practiceLastResultMessage }}
            </div>
          </div>

          <div class="summary-grid" style="margin-top: 0.7rem;">
            <div class="summary-cell"><strong>{{ practiceScore }}</strong><div class="muted">Score</div></div>
            <div class="summary-cell"><strong>{{ practiceCorrectCount }}</strong><div class="muted">Correct</div></div>
            <div class="summary-cell"><strong>{{ practiceIncorrectCount }}</strong><div class="muted">Incorrect</div></div>
            <div class="summary-cell"><strong>{{ practiceStreak }}</strong><div class="muted">Current Streak</div></div>
            <div class="summary-cell"><strong>{{ practiceBestStreak }}</strong><div class="muted">Best Streak</div></div>
            <div class="summary-cell"><strong>{{ practiceAccuracyPercent }}%</strong><div class="muted">Accuracy</div></div>
            <div class="summary-cell"><strong>{{ practiceAverageSeconds }}s</strong><div class="muted">Avg Time</div></div>
            <div class="summary-cell"><strong>+{{ practiceLastSpeedBonus }}</strong><div class="muted">Last Speed Bonus</div></div>
          </div>

          <div class="table-wrap" style="margin-top: 0.7rem;" v-if="practiceSummaryRows.length">
            <table>
              <thead>
                <tr>
                  <th>Prompt</th>
                  <th>Expected</th>
                  <th>Selected</th>
                  <th>Result</th>
                  <th>Time</th>
                  <th>Points</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, index) in practiceSummaryRows" :key="`${row.prompt}-${index}`">
                  <td>{{ row.prompt }}</td>
                  <td>{{ row.expectedLabel }}</td>
                  <td>{{ row.selectedLabel }}</td>
                  <td :class="row.correct ? 'status-success' : 'status-error'">
                    {{ row.correct ? "Correct" : "Incorrect" }}
                  </td>
                  <td>{{ row.elapsed_seconds.toFixed(2) }}s</td>
                  <td>{{ row.delta_points >= 0 ? `+${row.delta_points}` : row.delta_points }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section v-if="activeTab === 'tools'" class="grid">
        <div class="panel">
          <h2>Image Scan to Deck</h2>
          <div class="grid grid-3">
            <div class="field">
              <label>Destination Deck</label>
              <select v-model="scanDeckId">
                <option value="">Select deck...</option>
                <option v-for="deck in decks" :key="deck.id" :value="deck.id">
                  {{ deck.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>Schema</label>
              <select v-model="scanSchemaKey">
                <option v-for="schema in cardSchemas" :key="schema.key" :value="schema.key">
                  {{ schema.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>Word Form</label>
              <select v-model="scanWordForm">
                <option v-for="form in verbForms" :key="form.key" :value="form.key">
                  {{ form.label }}
                </option>
              </select>
            </div>
          </div>

          <div class="field" style="margin-top: 0.65rem;">
            <label>Tags</label>
            <input v-model="scanTags" placeholder="image_ocr,reading_practice" />
          </div>

          <div class="toolbar" style="margin-top: 0.65rem;">
            <UButton variant="soft" :disabled="Boolean(busyAction)" @click="pickScanImages">
              Pick Images
            </UButton>
            <UButton :disabled="Boolean(busyAction)" @click="runImageScan">
              Run Scan
            </UButton>
            <span class="muted">{{ scanImagePaths.length }} images selected</span>
          </div>
          <ul class="file-list" v-if="scanImagePaths.length">
            <li v-for="path in scanImagePaths" :key="path" class="mono">{{ path }}</li>
          </ul>

          <div class="field" v-if="scanSummary" style="margin-top: 0.65rem;">
            <label>Scan Summary</label>
            <textarea :value="scanSummary" readonly></textarea>
          </div>

          <div class="table-wrap" style="margin-top: 0.65rem;" v-if="scanPreviewRows.length">
            <table>
              <thead>
                <tr>
                  <th>Visible Text</th>
                  <th>Source Text</th>
                  <th>Entry ID</th>
                  <th>Word</th>
                  <th>Reading</th>
                  <th>English</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in scanPreviewRows" :key="`${row.visible_text}-${row.dictionary_entry_id}`">
                  <td>{{ row.visible_text }}</td>
                  <td>{{ row.source_text }}</td>
                  <td class="mono">{{ row.dictionary_entry_id }}</td>
                  <td>{{ row.kanji }}</td>
                  <td>{{ row.kana }}</td>
                  <td>{{ row.english }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="field" v-if="scanErrors.length" style="margin-top: 0.65rem;">
            <label>Scan Errors</label>
            <textarea :value="scanErrors.join('\n')" readonly></textarea>
          </div>
        </div>

        <div class="panel">
          <h2>CSV Import + Deck Export</h2>
          <div class="grid grid-2">
            <div class="field">
              <label>CSV Import Deck</label>
              <select v-model="importDeckId">
                <option value="">Select deck...</option>
                <option v-for="deck in decks" :key="deck.id" :value="deck.id">
                  {{ deck.label }}
                </option>
              </select>
              <div class="toolbar">
                <UButton size="sm" variant="soft" :disabled="Boolean(busyAction)" @click="pickCsvFile">
                  Pick CSV
                </UButton>
                <span class="mono muted">{{ importCsvPath || "No file selected" }}</span>
              </div>
              <UButton size="sm" :disabled="Boolean(busyAction)" @click="runCsvImport">
                Import CSV
              </UButton>
              <p class="muted" v-if="importCsvResult">{{ importCsvResult }}</p>
            </div>

            <div class="field">
              <label>Export Deck (.apkg)</label>
              <select v-model="exportDeckId">
                <option value="">Select deck...</option>
                <option v-for="deck in decks" :key="deck.id" :value="deck.id">
                  {{ deck.label }}
                </option>
              </select>
              <UButton size="sm" :disabled="Boolean(busyAction)" @click="runDeckExport">
                Export Deck
              </UButton>
              <p class="mono muted">{{ exportPath || "No export generated yet." }}</p>
            </div>
          </div>
        </div>
      </section>
    </div>
  </UApp>
</template>
