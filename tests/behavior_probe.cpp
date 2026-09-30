#include "pch.h"
#include "Game.h"
#include "behavior_probe.h"
#include <fstream>
#include <vector>

namespace
{
    struct Row { long long qpc; uint64_t ticks; uint32_t updates; int test; float remaining; bool flash; int patch; bool paused; };
    struct Log
    {
        std::vector<Row> rows;
        long long frequency = 0, start = 0;
        double seconds = 0;
        std::wstring path;
        int pattern = 0;
        Log()
        {
            wchar_t value[2048];
            if (GetEnvironmentVariableW(L"DISPLAYHDR_PROBE_LOG", value, 2048)) path = value;
            if (GetEnvironmentVariableW(L"DISPLAYHDR_PROBE_SECONDS", value, 2048)) seconds = _wtof(value);
            if (GetEnvironmentVariableW(L"DISPLAYHDR_PROBE_PATTERN", value, 2048)) pattern = _wtoi(value);
            LARGE_INTEGER clock; QueryPerformanceFrequency(&clock); frequency = clock.QuadPart;
            rows.reserve(100000);
        }
        ~Log()
        {
            if (path.empty()) return;
            std::ofstream output(path);
            output << "qpc,ticks,updates,test,remaining,flash,patch,paused\n";
            output.precision(10);
            for (auto const& row : rows)
                output << row.qpc / double(frequency) << ',' << row.ticks << ',' << row.updates
                << ',' << row.test << ',' << row.remaining << ',' << row.flash << ',' << row.patch << ',' << row.paused << '\n';
        }
    };
}

void BehaviorProbe::Record(Game& game)
{
    static Log log;
    LARGE_INTEGER clock; QueryPerformanceCounter(&clock);
    if (!log.start)
    {
        log.start = clock.QuadPart;
        game.m_showExplanatoryText = false;
        game.SetTestPattern(static_cast<Game::TestPattern>(log.pattern));
    }
    if (log.rows.size() < 100000)
        log.rows.push_back({clock.QuadPart, game.m_timer.GetTotalTicks(), game.m_timer.GetFrameCount(),
            static_cast<int>(game.m_currentTest), game.m_testTimeRemainingSec, game.m_flashOn != 0,
            game.m_currentXRiteIndex, game.m_bPaused});
    if (log.seconds > 0 && (clock.QuadPart - log.start) / double(log.frequency) >= log.seconds)
        PostQuitMessage(0);
}
