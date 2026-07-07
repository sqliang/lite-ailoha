import SwiftUI
import PhotosUI

struct ContentView: View {
    @StateObject private var vm = AnalysisViewModel()
    @State private var pickerItem: PhotosPickerItem?
    @State private var imageData: Data?
    @State private var supplementText: String = ""
    @State private var showCamera = false
    @State private var showStructure = false

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                ScrollView {
                    VStack(spacing: 20) {
                        uploadSection
                        textSection
                        analyzeButton
                        if vm.hasStructure { structureSection }
                        if !vm.cards.isEmpty || vm.isAnalyzing { resultSection }
                        if !vm.insight.isEmpty { insightSection }
                    }.padding()
                }
                if let toast = vm.toastMessage {
                    ToastView(message: toast, success: vm.toastIsSuccess)
                        .transition(.move(edge: .top).combined(with: .opacity)).padding(.top, 8)
                }
            }
            .animation(.spring(), value: vm.toastMessage)
            .navigationTitle("Lite Ailoha")
        }
        .onChange(of: pickerItem) { _, newItem in
            Task { if let data = try? await newItem?.loadTransferable(type: Data.self) { imageData = ImageProcessor().process(data) } }
        }
        .sheet(isPresented: $showCamera) { CameraPicker(imageData: $imageData) }
    }

    private var uploadSection: some View {
        VStack(spacing: 12) {
            if let data = imageData, let uiImage = UIImage(data: data) {
                Image(uiImage: uiImage).resizable().scaledToFit().frame(maxHeight: 200).clipShape(RoundedRectangle(cornerRadius: 12))
            }
            HStack(spacing: 12) {
                PhotosPicker(selection: $pickerItem, matching: .images) {
                    Label("相册", systemImage: "photo.on.rectangle").frame(maxWidth: .infinity).padding(.vertical, 12)
                        .background(Color(.secondarySystemBackground)).clipShape(RoundedRectangle(cornerRadius: 12))
                }
                Button { showCamera = true } label: {
                    Label("拍照", systemImage: "camera").frame(maxWidth: .infinity).padding(.vertical, 12)
                        .background(Color(.secondarySystemBackground)).clipShape(RoundedRectangle(cornerRadius: 12))
                }
            }
        }
    }

    private var textSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("补充说明").font(.subheadline).foregroundStyle(.secondary)
            TextEditor(text: $supplementText).frame(height: 60).padding(8)
                .background(Color(.secondarySystemBackground)).clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    private var analyzeButton: some View {
        Button { vm.startAnalysis(imageData: imageData, userContext: supplementText) } label: {
            HStack {
                if vm.isAnalyzing { ProgressView().tint(.white) }
                Text(vm.isAnalyzing ? "分析中…" : "开始分析")
            }
            .font(.headline).frame(maxWidth: .infinity).padding(.vertical, 14)
            .background(vm.isAnalyzing ? Color.gray : Color.accentColor)
            .foregroundStyle(.white).clipShape(RoundedRectangle(cornerRadius: 12))
        }.disabled(vm.isAnalyzing)
    }

    private var structureSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button { withAnimation { showStructure.toggle() } } label: {
                HStack {
                    Label("结构化对话", systemImage: "text.bubble").font(.subheadline.bold()); Spacer()
                    Text(vm.structure?.participants.joined(separator: " & ") ?? "").font(.caption).foregroundStyle(.secondary)
                    Image(systemName: showStructure ? "chevron.down" : "chevron.right").font(.caption).foregroundStyle(.secondary)
                }
            }
            if showStructure, let sp = vm.structure {
                ForEach(sp.messages, id: \.time) { msg in
                    HStack(alignment: .top, spacing: 8) {
                        Text(msg.time.suffix(8)).font(.caption2).foregroundStyle(.secondary).frame(width: 50, alignment: .trailing)
                        Text(msg.speaker).font(.caption).foregroundStyle(.blue).frame(width: 60, alignment: .leading)
                        Text(msg.content).font(.caption); Spacer()
                    }
                }
            }
        }.padding().background(Color(.secondarySystemBackground)).clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private var resultSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("分析结果").font(.headline)
            ForEach(vm.cards) { card in
                ActionCardView(card: card, typeLabel: vm.typeLabel(card.type),
                               onConfirm: { vm.confirm(card) }, onCancel: { vm.cancel(card) })
            }
        }
    }

    private var insightSection: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "lightbulb.fill").foregroundStyle(.yellow); Text(vm.insight).font(.callout)
        }.padding().frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.secondarySystemBackground)).clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

#Preview { ContentView() }
