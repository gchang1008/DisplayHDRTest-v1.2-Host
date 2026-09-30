#include "pch.h"
#include "Game.h"
#include <winrt/Windows.Foundation.Collections.h>
#include <iostream>
#include <fstream>
#if __has_include("AutomationPipe.h")
#include "AutomationPipe.h"
#define HAS_AUTOMATION 1
#endif

namespace
{
    bool capture = false;
    uint64_t pixelsHash = 0;
}

LRESULT CALLBACK TestWindowProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(window, message, wparam, lparam);
}

void RenderProbe::Capture(Game& game)
{
    if (!capture) return;
    auto resources = game.m_deviceResources.get();
    auto source = resources->GetRenderTarget();
    D3D11_TEXTURE2D_DESC desc;
    source->GetDesc(&desc);
    desc.Usage = D3D11_USAGE_STAGING;
    desc.BindFlags = 0;
    desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    desc.MiscFlags = 0;
    Microsoft::WRL::ComPtr<ID3D11Texture2D> staging;
    DX::ThrowIfFailed(resources->GetD3DDevice()->CreateTexture2D(&desc, nullptr, &staging));
    auto context = resources->GetD3DDeviceContext();
    context->CopyResource(staging.Get(), source);
    D3D11_MAPPED_SUBRESOURCE mapped;
    DX::ThrowIfFailed(context->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped));
    pixelsHash = 14695981039346656037ull;
    auto data = static_cast<unsigned char const*>(mapped.pData);
    for (unsigned y = 0; y < desc.Height; ++y)
        for (unsigned x = 0; x < desc.Width * 8; ++x)
            pixelsHash = (pixelsHash ^ data[y * mapped.RowPitch + x]) * 1099511628211ull;
    context->Unmap(staging.Get(), 0);
}

struct RegressionRunner
{
    static void Faults(Game& game, bool api)
    {
        game.m_showExplanatoryText = false;
        game.m_bPaused = true;
        capture = true;
        DX::StepTimer timer;
        int sample = 0;
        auto emit = [&]() {
            game.Render();
            std::cout << sample++ << ' ' << pixelsHash << ' ' << static_cast<int>(game.m_currentTest)
                << ' ' << game.m_currentColor << ' ' << game.m_bPaused << '\n';
        };
        for (auto pattern : { Game::TestPattern::ColorPatches, Game::TestPattern::TenPercentPeak,
            Game::TestPattern::SubTitleFlicker, Game::TestPattern::AnimatedColorGradient })
        {
            Prepare(game, pattern, timer, api);
            emit();
            for (auto& item : game.m_testPatternResources) {
                item.second.imageIsValid = false;
                item.second.effectIsValid = false;
            }
            emit();
#ifdef HAS_AUTOMATION
            if (api) {
            auto state = game.AutomationState().GetNamedObject(L"presentation");
            if (pattern == Game::TestPattern::TenPercentPeak && (state.GetNamedBoolean(L"resourcesValid") || state.GetNamedBoolean(L"submitted")))
                throw std::runtime_error("Invalid resources reported ready.");
            }
#endif
            game.m_deviceResources->HandleDeviceLost();
            emit();
#ifdef HAS_AUTOMATION
            if (api && !game.AutomationState().GetNamedObject(L"presentation").GetNamedBoolean(L"resourcesValid"))
                throw std::runtime_error("Restored resources reported invalid.");
#endif
            game.OnWindowSizeChanged(800, 600);
            emit();
            game.OnWindowSizeChanged(640, 480);
            emit();
            game.OnSuspending(); game.OnResuming();
            emit();
        }
    }

    static void Timing(Game& game, bool api)
    {
        game.m_showExplanatoryText = false;
        capture = true;
        DX::StepTimer timer;
        int sample = 0;
        auto emit = [&]()
        {
            game.Render();
            std::cout << sample++ << ' ' << static_cast<int>(game.m_currentTest) << ' '
                << game.m_testTimeRemainingSec << ' ' << game.m_flashOn << ' '
                << game.m_currentXRiteIndex << ' ' << game.m_XRitePatchAutoMode << ' '
                << game.m_bPaused << ' ' << game.m_totalTime << ' ' << pixelsHash << '\n';
        };
        for (auto pattern : { Game::TestPattern::WarmUp, Game::TestPattern::Cooldown,
            Game::TestPattern::TenPercentPeak, Game::TestPattern::TenPercentPeakMAX,
            Game::TestPattern::LongDurationWhite, Game::TestPattern::FullFramePeak,
            Game::TestPattern::FlashTest, Game::TestPattern::FlashTestMAX, Game::TestPattern::RiseFallTime,
            Game::TestPattern::XRiteColors, Game::TestPattern::ProfileCurve,
            Game::TestPattern::SubTitleFlicker, Game::TestPattern::LocalDimmingContrast,
            Game::TestPattern::AnimatedGrayGradient, Game::TestPattern::AnimatedColorGradient })
        {
            game.m_bPaused = false;
            game.m_flashOn = false;
            game.m_currentXRiteIndex = 0;
            game.m_currentProfileTile = 0;
            game.m_subtitleVisible = 1;
            game.m_LocalDimmingBars = 0;
            game.m_XRitePatchDisplayTime = 1;
            game.m_testTimeRemainingSec = 0;
            game.SetTestPattern(Game::TestPattern::ActiveDimming);
            timer.m_elapsedTicks = timer.m_totalTicks = 0;
            Prepare(game, pattern, timer, api);
            emit();
            if (pattern == Game::TestPattern::XRiteColors) game.ToggleXRitePatchAuto();
            for (int tick = 1; tick <= 3000; ++tick)
            {
                timer.m_elapsedTicks = DX::StepTimer::TicksPerSecond / 60;
                timer.m_totalTicks += timer.m_elapsedTicks;
                if (tick == 600 || tick == 900) game.PauseAnimation();
                game.Update(timer);
                // Render on phase transitions and evenly spaced animation samples.
                if (tick % 60 == 0 || tick <= 3) emit();
            }
            game.m_testTimeRemainingSec = 0.01f;
            game.Update(timer); emit();
            game.Update(timer); emit();
            // A deliberate restart must use the original initialization again.
            Prepare(game, pattern, timer, api); emit();
        }
    }

    static void Prepare(Game& game, Game::TestPattern pattern, DX::StepTimer& fixed, bool api)
    {
#ifdef HAS_AUTOMATION
        if (api)
        {
            using namespace winrt::Windows::Data::Json;
            JsonObject request, settings;
            auto catalog = game.AutomationCatalog();
            auto info = catalog.GetNamedArray(L"tests").GetAt(static_cast<uint32_t>(pattern)).GetObject();
            request.SetNamedValue(L"test", JsonValue::CreateStringValue(info.GetNamedString(L"id")));
            request.SetNamedValue(L"restart", JsonValue::CreateBooleanValue(true));
            auto current = game.AutomationSettings();
            for (auto const& name : game.AutomationApplicableSettings(pattern))
            {
                auto key = name.GetString();
                if (key == L"color" || key == L"checkerboard" || key == L"blackIndex" || key == L"profileIndex"
                    || key == L"xriteIndex" || key == L"whiteLevel" || key == L"subtitlesVisible" || key == L"dimmingMode")
                    settings.SetNamedValue(key, current.GetNamedValue(key));
            }
            if (settings.HasKey(L"color")) game.m_currentColor = (game.m_currentColor + 1) % 4;
            if (settings.HasKey(L"checkerboard")) game.m_checkerboard = static_cast<Game::Checkerboard>((static_cast<int>(game.m_checkerboard) + 1) % 3);
            if (settings.HasKey(L"blackIndex")) game.m_currentBlack = (game.m_currentBlack + 1) % 5;
            if (settings.HasKey(L"profileIndex")) game.m_currentProfileTile = 0;
            if (settings.HasKey(L"xriteIndex")) game.m_currentXRiteIndex = (game.m_currentXRiteIndex + 1) % 98;
            if (settings.HasKey(L"whiteLevel")) game.m_whiteLevelBracket = (game.m_whiteLevelBracket + 1) % 8;
            if (settings.HasKey(L"subtitlesVisible")) game.m_subtitleVisible = !game.m_subtitleVisible;
            if (settings.HasKey(L"dimmingMode")) game.m_LocalDimmingBars = !game.m_LocalDimmingBars;
            request.SetNamedValue(L"settings", settings);
            game.QueueAutomationState(request, L"regression");
            game.BeginAutomationUpdate();
        }
        else
#endif
            game.SetTestPattern(pattern);
        game.Update(fixed);
#ifdef HAS_AUTOMATION
        if (api) game.ApplyAutomationSettings();
#endif
    }

    static void Run(Game& game, bool api)
    {
        game.m_showExplanatoryText = false;
        game.m_bPaused = true;
        capture = true;
        DX::StepTimer fixed;
        for (int pattern = 0; pattern <= static_cast<int>(Game::TestPattern::Cooldown); ++pattern)
        {
            Prepare(game, static_cast<Game::TestPattern>(pattern), fixed, api);
            game.m_totalTime = 0;
            game.Render();
            std::cout << pattern << " " << pixelsHash << " " << game.m_Metadata.MaxContentLightLevel
                << " " << game.m_Metadata.MaxFrameAverageLightLevel << "\n";
        }
        int sample = 47;
        auto record = [&](Game::TestPattern pattern)
        {
            Prepare(game, pattern, fixed, api);
            game.m_totalTime = 0;
            game.Render();
            uint64_t metadataHash = 14695981039346656037ull;
            auto bytes = reinterpret_cast<unsigned char const*>(&game.m_Metadata);
            for (size_t i = 0; i < sizeof(game.m_Metadata); ++i) metadataHash = (metadataHash ^ bytes[i]) * 1099511628211ull;
            std::cout << sample++ << " " << pixelsHash << " " << metadataHash << "\n";
        };
        for (auto pattern : { Game::TestPattern::ColorPatches, Game::TestPattern::ColorPatchesFull,
            Game::TestPattern::ColorPatches709, Game::TestPattern::FullFrameSDRWhite,
            Game::TestPattern::FullFrameSDRWhiteWithHDR })
            for (int color = 0; color < 4; ++color) { game.m_currentColor = color; record(pattern); }
        for (auto pattern : { Game::TestPattern::StaticContrastRatio, Game::TestPattern::ActiveDimming,
            Game::TestPattern::ActiveDimmingDark, Game::TestPattern::ActiveDimmingSplit })
            for (int checker = 0; checker < 3; ++checker)
            { game.m_checkerboard = static_cast<Game::Checkerboard>(checker); record(pattern); }
        for (int black = 0; black < 5; ++black) { game.m_currentBlack = black; record(Game::TestPattern::BlackLevelCrush); }
        for (int subtitle = 0; subtitle < 2; ++subtitle) { game.m_subtitleVisible = subtitle; record(Game::TestPattern::SubTitleFlicker); }
        for (int bars = 0; bars < 2; ++bars) { game.m_LocalDimmingBars = bars; record(Game::TestPattern::LocalDimmingContrast); }
        for (int index : { 0, 1, 42, 97 })
            for (int bracket = 0; bracket < 8; ++bracket)
            { game.m_currentXRiteIndex = index; game.m_whiteLevelBracket = bracket; record(Game::TestPattern::XRiteColors); }
#ifdef HAS_AUTOMATION
        int maximum = game.AutomationProfileMaximum();
#else
        game.SetTestPattern(Game::TestPattern::ProfileCurve);
        game.Update(fixed); game.Render();
        int maximum = game.m_maxProfileTile;
#endif
        for (int tile = 0; tile <= maximum; ++tile) { game.m_currentProfileTile = tile; record(Game::TestPattern::ProfileCurve); }
        game.m_showExplanatoryText = true;
        for (auto pattern : { Game::TestPattern::ActiveDimming, Game::TestPattern::ActiveDimmingDark,
            Game::TestPattern::SubTitleFlicker, Game::TestPattern::ColorPatches, Game::TestPattern::ColorPatchesFull }) record(pattern);
    }
};

int wmain(int argc, wchar_t** argv)
{
    try
    {
        std::cout << std::unitbuf;
        winrt::init_apartment(winrt::apartment_type::multi_threaded);
        WNDCLASSW type = {};
        type.lpfnWndProc = TestWindowProc;
        type.hInstance = GetModuleHandleW(nullptr);
        type.lpszClassName = L"DisplayHDRAutomationTestWindow";
        RegisterClassW(&type);
        HWND window = CreateWindowW(type.lpszClassName, L"DisplayHDR API test", WS_OVERLAPPEDWINDOW,
            0, 0, 640, 480, nullptr, nullptr, type.hInstance, nullptr);
        if (!window) throw std::runtime_error("Test window creation failed.");
        Game game(const_cast<PWSTR>(L"DisplayHDR API test"));
        game.Initialize(window, 640, 480);
        Sleep(20);
        game.Tick();
        if (argc > 1 && (wcscmp(argv[1], L"--faults") == 0 || wcscmp(argv[1], L"--faults-api") == 0))
        {
            bool api = wcscmp(argv[1], L"--faults-api") == 0;
#ifdef HAS_AUTOMATION
            if (api) game.ConfigureAutomation(window, [](bool) {}, []() { return false; });
#endif
            RegressionRunner::Faults(game, api);
            DestroyWindow(window);
            return 0;
        }
        if (argc > 1 && (wcscmp(argv[1], L"--timing") == 0 || wcscmp(argv[1], L"--timing-api") == 0))
        {
            bool api = wcscmp(argv[1], L"--timing-api") == 0;
#ifdef HAS_AUTOMATION
            if (api) game.ConfigureAutomation(window, [](bool) {}, []() { return false; });
#endif
            RegressionRunner::Timing(game, api);
            DestroyWindow(window);
            return 0;
        }
        if (argc > 1 && (wcscmp(argv[1], L"--capture") == 0 || wcscmp(argv[1], L"--capture-api") == 0))
        {
            bool api = wcscmp(argv[1], L"--capture-api") == 0;
#ifdef HAS_AUTOMATION
            if (api) game.ConfigureAutomation(window, [](bool) {}, []() { return false; });
#endif
            RegressionRunner::Run(game, api);
            DestroyWindow(window);
            return 0;
        }
#ifdef HAS_AUTOMATION
        bool fullscreen = false;
        game.ConfigureAutomation(window, [&](bool value) { fullscreen = value; }, [&]() { return fullscreen; });
        AutomationPipe pipe;
        std::cout << GetCurrentProcessId() << std::endl;
        MSG message = {};
        while (message.message != WM_QUIT)
        {
            if (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE))
            { TranslateMessage(&message); DispatchMessageW(&message); }
            else { game.Tick(); pipe.Poll(game); }
        }
#endif
        DestroyWindow(window);
    }
    catch (winrt::hresult_error const& error)
    { std::cerr << "WinRT error: " << std::hex << error.code().value << " " << winrt::to_string(error.message()) << std::endl; return 1; }
    catch (std::exception const& error)
    { std::cerr << "Runtime error: " << error.what() << std::endl; return 1; }
    return 0;
}
