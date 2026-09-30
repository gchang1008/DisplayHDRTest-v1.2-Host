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
