// src/user/Live.jsx

import React, {
  useEffect,
  useState,
} from "react";

import {
  X,
  Radio,
  RefreshCw,
  Trophy,
  CircleDot,
} from "lucide-react";

import { useLive } from "../contexts/LiveContext";

export default function Live({
  open = false,
  onClose,
}) {
  const {
    matches,
    liveCount,
    connected,
    refresh,
  } = useLive();

  const [loading, setLoading] =
    useState(true);

  const [error, setError] =
    useState("");

  const [refreshing, setRefreshing] =
    useState(false);

  /*
   * ==========================================================
   * INITIAL / MANUAL REFRESH
   * ==========================================================
   */
  async function loadInitial(
    showLoader = true
  ) {
    try {
      if (showLoader) {
        setLoading(true);
      }

      setError("");

      await refresh();
    } catch (err) {
      console.error(
        "[Live] refresh failed:",
        err
      );

      setError(
        "Unable to load the latest scores."
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  /*
   * ==========================================================
   * INITIAL LOAD
   * ==========================================================
   */
  useEffect(() => {
    loadInitial();
  }, []);

  /*
   * ==========================================================
   * LOCK BODY SCROLL WHEN DRAWER IS OPEN
   * ==========================================================
   */
  useEffect(() => {
    if (!open) {
      return;
    }

    document.body.style.overflow =
      "hidden";

    return () => {
      document.body.style.overflow =
        "";
    };
  }, [open]);

  /*
   * ==========================================================
   * ESCAPE TO CLOSE
   * ==========================================================
   */
  useEffect(() => {
    const handleKeyDown = (event) => {
      if (
        event.key === "Escape" &&
        open
      ) {
        onClose?.();
      }
    };

    window.addEventListener(
      "keydown",
      handleKeyDown
    );

    return () => {
      window.removeEventListener(
        "keydown",
        handleKeyDown
      );
    };
  }, [open, onClose]);

  /*
   * ==========================================================
   * MANUAL REFRESH
   * ==========================================================
   */
  const handleRefresh = async () => {
    setRefreshing(true);

    await loadInitial(false);
  };

  /*
   * ==========================================================
   * MATCH STATUS LABEL
   * ==========================================================
   */
  const getStatusLabel = (match) => {
    const status = String(
      match?.status ?? ""
    ).toUpperCase();

    if (status === "PAUSED") {
      return "Half Time";
    }

    return "In Play";
  };

  return (
    <>
      {/* ======================================================
          BACKDROP
          ====================================================== */}
      <div
        className={`
          fixed inset-0 z-[80]
          bg-slate-950/70
          backdrop-blur-md
          transition-all duration-300
          ${
            open
              ? "opacity-100 pointer-events-auto"
              : "opacity-0 pointer-events-none"
          }
        `}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* ======================================================
          DRAWER
          ====================================================== */}
      <aside
        className={`
          fixed top-0 right-0 z-[90]
          h-full
          w-full
          sm:w-[430px]
          lg:w-[480px]
          bg-[#070b14]
          text-white
          shadow-2xl
          border-l border-white/[0.06]
          flex flex-col
          transition-transform duration-300 ease-out
          ${
            open
              ? "translate-x-0"
              : "translate-x-full"
          }
        `}
        role="dialog"
        aria-modal="true"
        aria-label="Live scores"
      >
        {/* ====================================================
            HEADER
            ==================================================== */}
        <header
          className="
            relative
            flex-shrink-0
            border-b border-white/[0.06]
            bg-[#090e19]/95
            backdrop-blur-xl
          "
        >
          {/* Subtle top accent */}
          <div
            className="
              absolute
              top-0
              left-0
              right-0
              h-px
              bg-gradient-to-r
              from-transparent
              via-red-500/70
              to-transparent
            "
          />

          <div className="px-5 pt-5 pb-4">
            <div className="flex items-center justify-between gap-3">
              {/* TITLE */}
              <div className="flex items-center gap-3">
                <div
                  className="
                    relative
                    flex
                    h-11
                    w-11
                    shrink-0
                    items-center
                    justify-center
                    rounded-2xl
                    bg-red-500/10
                    border
                    border-red-500/15
                  "
                >
                  <Radio
                    size={20}
                    strokeWidth={2.2}
                    className="text-red-400"
                  />

                  <span
                    className="
                      absolute
                      -right-0.5
                      -top-0.5
                      h-2.5
                      w-2.5
                      rounded-full
                      bg-red-500
                      border-2
                      border-[#090e19]
                      animate-pulse
                    "
                  />
                </div>

                <div>
                  <h2 className="text-xl font-black tracking-tight">
                    Live Scores
                  </h2>

                  <p className="mt-0.5 text-xs text-slate-500">
                    Follow the action as it happens
                  </p>
                </div>
              </div>

              {/* ACTIONS */}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleRefresh}
                  disabled={refreshing}
                  className="
                    flex
                    h-10
                    w-10
                    items-center
                    justify-center
                    rounded-xl
                    border
                    border-white/[0.07]
                    bg-white/[0.035]
                    text-slate-400
                    transition-all
                    hover:bg-white/[0.07]
                    hover:text-white
                    active:scale-95
                    disabled:cursor-not-allowed
                    disabled:opacity-40
                  "
                  aria-label="Refresh scores"
                >
                  <RefreshCw
                    size={17}
                    className={
                      refreshing
                        ? "animate-spin"
                        : ""
                    }
                  />
                </button>

                <button
                  type="button"
                  onClick={onClose}
                  className="
                    flex
                    h-10
                    w-10
                    items-center
                    justify-center
                    rounded-xl
                    border
                    border-white/[0.07]
                    bg-white/[0.035]
                    text-slate-400
                    transition-all
                    hover:bg-red-500/10
                    hover:border-red-500/20
                    hover:text-red-400
                    active:scale-95
                  "
                  aria-label="Close"
                >
                  <X size={19} />
                </button>
              </div>
            </div>

            {/* SUMMARY BAR */}
            <div
              className="
                mt-5
                flex
                items-center
                justify-between
                rounded-2xl
                border
                border-white/[0.06]
                bg-white/[0.025]
                px-4
                py-3
              "
            >
              <div className="flex items-center gap-2.5">
                <div
                  className={`
                    flex
                    h-7
                    w-7
                    items-center
                    justify-center
                    rounded-lg
                    ${
                      liveCount > 0
                        ? "bg-red-500/10"
                        : "bg-white/[0.04]"
                    }
                  `}
                >
                  <CircleDot
                    size={14}
                    className={
                      liveCount > 0
                        ? "text-red-400"
                        : "text-slate-600"
                    }
                  />
                </div>

                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-600">
                    Now
                  </p>

                  <p className="text-sm font-bold text-slate-200">
                    {liveCount}{" "}
                    {liveCount === 1
                      ? "match"
                      : "matches"}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <span
                  className={`
                    h-2
                    w-2
                    rounded-full
                    ${
                      connected
                        ? "bg-emerald-400 animate-pulse"
                        : "bg-slate-600"
                    }
                  `}
                />

                <span className="text-[10px] font-semibold text-slate-500">
                  {connected
                    ? "Updated automatically"
                    : "Updating..."}
                </span>
              </div>
            </div>
          </div>
        </header>

        {/* ====================================================
            CONTENT
            ==================================================== */}
        <main
          className="
            flex-1
            overflow-y-auto
            overscroll-contain
            px-4
            py-5
            sm:px-5
          "
        >
          {/* ==================================================
              LOADING
              ================================================== */}
          {loading && (
            <div className="flex min-h-[420px] items-center justify-center">
              <div className="text-center">
                <div
                  className="
                    mx-auto
                    mb-5
                    flex
                    h-14
                    w-14
                    items-center
                    justify-center
                    rounded-2xl
                    bg-red-500/10
                    border
                    border-red-500/10
                  "
                >
                  <RefreshCw
                    size={21}
                    className="
                      animate-spin
                      text-red-400
                    "
                  />
                </div>

                <p className="text-sm font-semibold text-slate-300">
                  Loading scores
                </p>

                <p className="mt-1 text-xs text-slate-600">
                  Getting the latest matches...
                </p>
              </div>
            </div>
          )}

          {/* ==================================================
              ERROR
              ================================================== */}
          {!loading && error && (
            <div className="flex min-h-[420px] items-center justify-center">
              <div
                className="
                  w-full
                  rounded-3xl
                  border
                  border-red-500/10
                  bg-red-500/[0.04]
                  p-7
                  text-center
                "
              >
                <div
                  className="
                    mx-auto
                    mb-4
                    flex
                    h-14
                    w-14
                    items-center
                    justify-center
                    rounded-2xl
                    bg-red-500/10
                    text-xl
                  "
                >
                  !
                </div>

                <h3 className="font-bold text-red-300">
                  Something went wrong
                </h3>

                <p className="mt-2 text-xs leading-5 text-slate-500">
                  {error}
                </p>

                <button
                  type="button"
                  onClick={handleRefresh}
                  disabled={refreshing}
                  className="
                    mt-5
                    inline-flex
                    items-center
                    gap-2
                    rounded-xl
                    bg-red-500
                    px-4
                    py-2.5
                    text-xs
                    font-bold
                    text-white
                    shadow-lg
                    shadow-red-500/10
                    transition
                    hover:bg-red-400
                    active:scale-95
                    disabled:opacity-50
                  "
                >
                  <RefreshCw
                    size={14}
                    className={
                      refreshing
                        ? "animate-spin"
                        : ""
                    }
                  />

                  Try again
                </button>
              </div>
            </div>
          )}

          {/* ==================================================
              EMPTY STATE
              ================================================== */}
          {!loading &&
            !error &&
            matches.length === 0 && (
              <div className="flex min-h-[420px] items-center justify-center">
                <div className="w-full text-center">
                  <div
                    className="
                      mx-auto
                      mb-5
                      flex
                      h-20
                      w-20
                      items-center
                      justify-center
                      rounded-[26px]
                      border
                      border-white/[0.06]
                      bg-white/[0.025]
                    "
                  >
                    <Trophy
                      size={30}
                      strokeWidth={1.5}
                      className="text-slate-600"
                    />
                  </div>

                  <h3 className="text-lg font-black text-slate-200">
                    Nothing playing right now
                  </h3>

                  <p className="mx-auto mt-2 max-w-[280px] text-sm leading-6 text-slate-600">
                    When a match gets underway,
                    the score will appear here
                    automatically.
                  </p>

                  <div
                    className="
                      mx-auto
                      mt-6
                      inline-flex
                      items-center
                      gap-2
                      rounded-full
                      border
                      border-white/[0.05]
                      bg-white/[0.025]
                      px-3
                      py-2
                    "
                  >
                    <span
                      className={`
                        h-1.5
                        w-1.5
                        rounded-full
                        ${
                          connected
                            ? "bg-emerald-400 animate-pulse"
                            : "bg-slate-600"
                        }
                      `}
                    />

                    <span className="text-[10px] font-semibold text-slate-600">
                      Scores will update automatically
                    </span>
                  </div>
                </div>
              </div>
            )}

          {/* ==================================================
              MATCH LIST
              ================================================== */}
          {!loading &&
            !error &&
            matches.length > 0 && (
              <div className="space-y-4">
                {matches.map((match) => {
                  const key =
                    match.match_id ??
                    `${match.home_team_name}-${match.away_team_name}`;

                  const isPaused =
                    String(
                      match.status ?? ""
                    ).toUpperCase() ===
                    "PAUSED";

                  return (
                    <article
                      key={key}
                      className="
                        group
                        overflow-hidden
                        rounded-[24px]
                        border
                        border-white/[0.07]
                        bg-[#0d1320]
                        shadow-xl
                        shadow-black/20
                        transition-all
                        hover:border-white/[0.11]
                      "
                    >
                      {/* MATCH HEADER */}
                      <div
                        className="
                          flex
                          items-center
                          justify-between
                          border-b
                          border-white/[0.05]
                          px-4
                          py-3.5
                        "
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className="
                              relative
                              flex
                              h-7
                              w-7
                              items-center
                              justify-center
                              rounded-lg
                              bg-red-500/10
                            "
                          >
                            <span
                              className="
                                h-2
                                w-2
                                rounded-full
                                bg-red-500
                                animate-pulse
                              "
                            />
                          </span>

                          <div>
                            <p className="text-[10px] font-black uppercase tracking-widest text-red-400">
                              {isPaused
                                ? "Half Time"
                                : "Live"}
                            </p>

                            <p className="mt-0.5 text-[9px] text-slate-600">
                              {getStatusLabel(
                                match
                              )}
                            </p>
                          </div>
                        </div>

                        <span
                          className="
                            rounded-full
                            border
                            border-white/[0.05]
                            bg-white/[0.035]
                            px-2.5
                            py-1.5
                            text-[9px]
                            font-bold
                            text-slate-500
                          "
                        >
                          {match.status}
                        </span>
                      </div>

                      {/* MATCH BODY */}
                      <div className="px-4 py-6 sm:px-5">
                        <div
                          className="
                            grid
                            grid-cols-[1fr_auto_1fr]
                            items-center
                            gap-3
                          "
                        >
                          {/* HOME TEAM */}
                          <div className="min-w-0 text-right">
                            <div
                              className="
                                flex
                                min-h-[44px]
                                items-center
                                justify-end
                              "
                            >
                              <p
                                className="
                                  break-words
                                  text-sm
                                  font-extrabold
                                  leading-5
                                  text-white
                                  sm:text-[15px]
                                "
                              >
                                {
                                  match.home_team_name
                                }
                              </p>
                            </div>

                            <p
                              className="
                                mt-2
                                text-[8px]
                                font-bold
                                uppercase
                                tracking-[0.18em]
                                text-slate-700
                              "
                            >
                              Home
                            </p>
                          </div>

                          {/* SCORE */}
                          <div className="flex flex-col items-center">
                            <div
                              className="
                                flex
                                min-w-[104px]
                                items-center
                                justify-center
                                rounded-2xl
                                border
                                border-white/[0.07]
                                bg-[#070b14]
                                px-3
                                py-3
                              "
                            >
                              <span className="text-3xl font-black leading-none text-white">
                                {
                                  match.home_score
                                }
                              </span>

                              <span className="mx-2 text-lg font-bold text-slate-700">
                                :
                              </span>

                              <span className="text-3xl font-black leading-none text-white">
                                {
                                  match.away_score
                                }
                              </span>
                            </div>

                            <div className="mt-2 flex items-center gap-1.5">
                              <span
                                className="
                                  h-1.5
                                  w-1.5
                                  rounded-full
                                  bg-red-500
                                  animate-pulse
                                "
                              />

                              <span className="text-[8px] font-black uppercase tracking-widest text-red-400">
                                {isPaused
                                  ? "HT"
                                  : "Playing"}
                              </span>
                            </div>
                          </div>

                          {/* AWAY TEAM */}
                          <div className="min-w-0 text-left">
                            <div
                              className="
                                flex
                                min-h-[44px]
                                items-center
                                justify-start
                              "
                            >
                              <p
                                className="
                                  break-words
                                  text-sm
                                  font-extrabold
                                  leading-5
                                  text-white
                                  sm:text-[15px]
                                "
                              >
                                {
                                  match.away_team_name
                                }
                              </p>
                            </div>

                            <p
                              className="
                                mt-2
                                text-[8px]
                                font-bold
                                uppercase
                                tracking-[0.18em]
                                text-slate-700
                              "
                            >
                              Away
                            </p>
                          </div>
                        </div>
                      </div>

                      {/* MATCH FOOTER */}
                      <div
                        className="
                          flex
                          items-center
                          justify-center
                          border-t
                          border-white/[0.04]
                          bg-white/[0.015]
                          px-4
                          py-2.5
                        "
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className="
                              h-1.5
                              w-1.5
                              rounded-full
                              bg-emerald-400
                              animate-pulse
                            "
                          />

                          <span className="text-[9px] font-semibold text-slate-600">
                            Score updating automatically
                          </span>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
        </main>

        {/* ====================================================
            FOOTER
            ==================================================== */}
        <footer
          className="
            flex-shrink-0
            border-t
            border-white/[0.06]
            bg-[#090e19]
            px-5
            py-3.5
          "
        >
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-medium text-slate-700">
              Stay up to date with the action
            </span>

            <div className="flex items-center gap-1.5">
              <span
                className={`
                  h-1.5
                  w-1.5
                  rounded-full
                  ${
                    connected
                      ? "bg-emerald-400"
                      : "bg-slate-600"
                  }
                `}
              />

              <span className="text-[9px] font-bold uppercase tracking-wider text-slate-600">
                {connected
                  ? "Updated"
                  : "Updating"}
              </span>
            </div>
          </div>
        </footer>
      </aside>
    </>
  );
}
