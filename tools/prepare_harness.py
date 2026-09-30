"""Replace display-dependent boundaries only in an isolated test build."""
from pathlib import Path
import re
import sys

stage = Path(sys.argv[1])


def body(source, name, replacement):
    start = source.index(name)
    opening = source.index("{", start)
    depth = 0
    tokens = re.finditer(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\{|\}', source[opening:], re.S)
    for token in tokens:
        if token.group() == "{":
            depth += 1
        elif token.group() == "}":
            depth -= 1
            if depth == 0:
                end = opening + token.end()
                return source[:opening] + "{\n" + replacement + "\n}" + source[end:]
    raise ValueError(f"Function boundary not found: {name}")


device_path = stage / "DeviceResources.cpp"
device = device_path.read_bytes().decode("cp1252")
start = device.index("    ComPtr<IDXGIAdapter1> adapter;", device.index("void DX::DeviceResources::CreateDeviceResources()"))
end = device.index("    // Store pointers to the Direct3D", start)
device = device[:start] + """
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    DX::ThrowIfFailed(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr,
        creationFlags, s_featureLevels, ARRAYSIZE(s_featureLevels), D3D11_SDK_VERSION,
        &device, &m_d3dFeatureLevel, &context));
""" + device[end:]
device = body(device, "void DX::DeviceResources::CreateWindowSizeDependentResources()", """
    UpdateLogicalSize(m_outputSize, m_dpi);
    CD3D11_TEXTURE2D_DESC texture(m_backBufferFormat, m_outputSize.right, m_outputSize.bottom,
        1, 1, D3D11_BIND_RENDER_TARGET);
    DX::ThrowIfFailed(m_d3dDevice->CreateTexture2D(&texture, nullptr, &m_renderTarget));
    DX::ThrowIfFailed(m_d3dDevice->CreateRenderTargetView(m_renderTarget.Get(), nullptr, &m_d3dRenderTargetView));
    CD3D11_TEXTURE2D_DESC depth(m_depthBufferFormat, m_outputSize.right, m_outputSize.bottom,
        1, 1, D3D11_BIND_DEPTH_STENCIL);
    DX::ThrowIfFailed(m_d3dDevice->CreateTexture2D(&depth, nullptr, &m_depthStencil));
    DX::ThrowIfFailed(m_d3dDevice->CreateDepthStencilView(m_depthStencil.Get(), nullptr, &m_d3dDepthStencilView));
    m_screenViewport = CD3D11_VIEWPORT(0.f, 0.f, float(m_outputSize.right), float(m_outputSize.bottom));
    m_d3dContext->RSSetViewports(1, &m_screenViewport);
    ComPtr<IDXGISurface> surface;
    DX::ThrowIfFailed(m_renderTarget.As(&surface));
    auto properties = D2D1::BitmapProperties1(D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW,
        D2D1::PixelFormat(m_backBufferFormat, D2D1_ALPHA_MODE_PREMULTIPLIED), m_dpi, m_dpi);
    DX::ThrowIfFailed(m_d2dContext->CreateBitmapFromDxgiSurface(surface.Get(), &properties, &m_d2dTargetBitmap));
    m_d2dContext->SetTarget(m_d2dTargetBitmap.Get());
    m_d2dContext->SetDpi(m_dpi, m_dpi);
""")
present = "m_lastPresentResult = S_OK;" if b"m_lastPresentResult" in (stage / "DeviceResources.h").read_bytes() else ""
device = body(device, "void DX::DeviceResources::Present()", present)
device_path.write_bytes(device.encode("cp1252"))

game_path = stage / "Game.cpp"
game = game_path.read_bytes().decode("cp1252")
game = body(game, "void Game::UpdateDxgiColorimetryInfo()", r"""
    m_outputDesc = {};
    wcscpy_s(m_outputDesc.DeviceName, L"\\\\.\\DISPLAY1");
    m_adapterDesc = {};
    wcscpy_s(m_adapterDesc.Description, L"Software regression fixture");
    m_monitorName = L"Regression fixture";
    m_connectionKind = winrt::Windows::Devices::Display::DisplayMonitorConnectionKind::Virtual;
    m_physicalConnectorKind = winrt::Windows::Devices::Display::DisplayMonitorPhysicalConnectorKind::Unknown;
    m_outputDesc.RedPrimary[0] = .64f; m_outputDesc.RedPrimary[1] = .33f;
    m_outputDesc.GreenPrimary[0] = .30f; m_outputDesc.GreenPrimary[1] = .60f;
    m_outputDesc.BluePrimary[0] = .15f; m_outputDesc.BluePrimary[1] = .06f;
    m_outputDesc.WhitePoint[0] = .31271f; m_outputDesc.WhitePoint[1] = .32902f;
    m_outputDesc.MaxLuminance = 1000.f; m_outputDesc.MaxFullFrameLuminance = 500.f;
    m_outputDesc.MinLuminance = .0001f;
    wchar_t sdr[8];
    m_outputDesc.ColorSpace = GetEnvironmentVariableW(L"DISPLAYHDR_TEST_SDR", sdr, 8)
        ? DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709 : DXGI_COLOR_SPACE_RGB_FULL_G2084_NONE_P2020;
    m_rawOutDesc = { 1000.f, 500.f, .0001f };
    m_modeWidth = 640; m_modeHeight = 480;
    m_maxPQCode = UINT32(roundf(1023.f * Apply2084(.1f)));
    if (CheckHDR_On()) m_staticContrastPQValue = Apply2084(.05f) * 1023.f;
    else m_staticContrastsRGBValue = (500.f / 270.f) * 255.f;
    m_dxgiColorInfoStale = false;
""")
game = body(game, "float randf_s()", "return 0.5f; // Deterministic jitter input for paired image comparisons.")
game = re.sub(r'DX::ThrowIfFailed\(sc->SetHDRMetaData\(DXGI_HDR_METADATA_TYPE_HDR10, sizeof\(DXGI_HDR_METADATA_HDR10\), &m_Metadata\)\);',
              '/* Metadata remains in Game for test assertions; there is no physical display. */', game)
game_path.write_bytes(game.encode("cp1252"))
